// Data status, sync and settings (mock-ups 9 and 10). Sync time and bank-data freshness are shown
// apart (shared-contract §5); a failed sync keeps the last valid snapshot and says so.

import CommonCentsKit
import SwiftUI
import VisionKit

struct SyncView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        List {
            Section {
                Button {
                    Task { await model.syncNow() }
                } label: {
                    HStack {
                        Text("Sync now").fontWeight(.semibold)
                        if model.syncing { Spacer(); ProgressView() }
                    }
                }
                .disabled(model.paired == nil || model.syncing)
                Text(model.paired == nil ? "Pair this phone with the Mac first, under Settings."
                                         : "The Mac must be awake, running pf sync serve, on this network.")
                    .font(.footnote).foregroundStyle(.secondary)
                if let error = model.lastError {
                    Text(error).font(.footnote).foregroundStyle(.red)
                }
            }
            if let snapshot = model.snapshot {
                Section("Bank data, per account") {
                    ForEach(snapshot.content.cutoff.accounts, id: \.accountIndex) { freshness in
                        Row(snapshot.account(freshness.accountIndex)?.displayName ?? "Account",
                            freshness.lastCoveredDay.map { "through \(Dates.shortDay($0))" } ?? "No complete coverage",
                            note: freshness.lastImportDate.map { "imported \(Dates.shortDay($0))" })
                    }
                }
                Section("Review on the Mac") {
                    Row("Possible duplicates", "\(snapshot.content.review.possibleDuplicate)")
                    Row("Unresolved records", "\(snapshot.content.review.unresolvedRecord)")
                }
            }
            Section("Sync history") {
                if model.history.isEmpty { Text("No sync yet").foregroundStyle(.secondary) }
                ForEach(model.history) { event in
                    VStack(alignment: .leading) {
                        Row(event.at.formatted(date: .abbreviated, time: .shortened),
                            event.outcome == .installed ? "Installed" : "Failed")
                        if event.outcome == .failed {
                            Text("\(event.detail) The last valid snapshot was kept.").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
            }
            Section { NavigationLink("Settings") { SettingsView() } }
        }
        .navigationTitle("Data status")
    }
}

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @State private var confirmingDelete = false

    var body: some View {
        @Bindable var model = model
        List {
            Section("Paired Mac") {
                if let paired = model.paired {
                    Row("Mac", "Paired \(paired.pairedAt.formatted(date: .abbreviated, time: .omitted))")
                    Row("Fingerprint", stride(from: 0, to: 12, by: 4).map { start in
                        String(Array(paired.fingerprint)[start..<start + 4]).uppercased()
                    }.joined(separator: " · "))
                    Row("Address", "\(paired.address):\(paired.port)")
                } else {
                    Text("Not paired").foregroundStyle(.secondary)
                }
                NavigationLink(model.paired == nil ? "Pair with the Mac" : "Pair again") { PairView() }
            }
            Section("View") {
                Picker("Default view", selection: $model.defaultView) {
                    Text("Household").tag(ViewScope.household)
                    ForEach(model.snapshot?.content.household.members ?? []) { member in
                        Text(member.name).tag(ViewScope.member(member.memberIndex))
                    }
                }
                Stepper("Warn when older than \(model.staleThresholdHours) hours",
                        value: $model.staleThresholdHours, in: 1...168)
                Row("Lock after", "1 minute in the background")
            }
            Section(header: Text("This phone's data"),
                    footer: Text("Deleting removes the snapshot and the pairing. The Mac's ledger is untouched. Reinstalling the app also removes them, and the phone then pairs again.")) {
                if let snapshot = model.snapshot {
                    Row("Snapshot", "\(model.store.installedBytes.map { ByteCountFormatter.string(fromByteCount: Int64($0), countStyle: .file) } ?? "demo") · \(Dates.shortDay(snapshot.content.cutoff.asOf))")
                }
                Button("Delete local data", role: .destructive) { confirmingDelete = true }
            }
        }
        .navigationTitle("Settings")
        .confirmationDialog("Delete the snapshot and the pairing from this phone?", isPresented: $confirmingDelete,
                            titleVisibility: .visible) {
            Button("Delete", role: .destructive) { model.deleteLocalData() }
        }
    }
}

struct PairView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @State private var typed = ""
    @State private var scanning = false
    @State private var prefixToConfirm: String?
    @State private var answer: CheckedContinuation<Bool, Never>?

    var body: some View {
        List {
            Section(footer: Text("On the Mac, run pf sync pair with this phone's name. The code works once, for 120 seconds.")) {
                if DataScannerViewController.isSupported {
                    Button("Scan the QR code") { scanning = true }
                }
                TextField("Or type the code", text: $typed, axis: .vertical)
                    .textInputAutocapitalization(.characters).autocorrectionDisabled()
                Button("Pair") { pair(typed) }.disabled(PairingCode.parsed(typed) == nil)
            }
            Section(footer: Text("If the Mac's address changed, scan the code pf sync serve shows. It holds no secret.")) {
                Button("Use a reconnect code") { model.reconnect(typed) }
                    .disabled(PairingCode.reconnection(typed) == nil || model.paired == nil)
            }
            if let error = model.lastError { Text(error).font(.footnote).foregroundStyle(.red) }
        }
        .navigationTitle("Pair")
        .sheet(isPresented: $scanning) {
            QRScanner { text in
                scanning = false
                typed = text
                if PairingCode.parsed(text) != nil { pair(text) }
            }
        }
        .alert("Does the Mac show \(prefixToConfirm ?? "")?", isPresented: Binding(
            get: { prefixToConfirm != nil }, set: { if !$0 { prefixToConfirm = nil } })) {
            Button("It matches") { answer?.resume(returning: true); answer = nil; prefixToConfirm = nil }
            Button("It does not", role: .cancel) { answer?.resume(returning: false); answer = nil; prefixToConfirm = nil }
        } message: {
            Text("Compare these 16 digits with the terminal's before trusting this Mac.")
        }
    }

    func pair(_ text: String) {
        guard let code = PairingCode.parsed(text) else { return }
        Task {
            await model.pair(code) { prefix in
                await withCheckedContinuation { continuation in
                    Task { @MainActor in
                        answer = continuation
                        prefixToConfirm = prefix
                    }
                }
            }
            if model.paired != nil, model.lastError == nil { dismiss() }
        }
    }
}

struct QRScanner: UIViewControllerRepresentable {
    let found: (String) -> Void

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let scanner = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])],
                                                isHighlightingEnabled: true)
        scanner.delegate = context.coordinator
        try? scanner.startScanning()
        return scanner
    }

    func updateUIViewController(_ controller: DataScannerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(found: found) }

    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        let found: (String) -> Void
        init(found: @escaping (String) -> Void) { self.found = found }

        func dataScanner(_ scanner: DataScannerViewController, didAdd items: [RecognizedItem],
                         allItems: [RecognizedItem]) {
            for case let .barcode(code) in items {
                if let text = code.payloadStringValue {
                    scanner.stopScanning()
                    found(text)
                    return
                }
            }
        }
    }
}
