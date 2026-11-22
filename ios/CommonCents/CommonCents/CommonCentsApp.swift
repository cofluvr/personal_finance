// CommonCents: a read-only companion to the Mac ledger (PRD-ios.md, D-079). Every figure comes
// from the installed snapshot as the backend wrote it. The app computes nothing but formatting
// and how old the snapshot is.

import CommonCentsKit
import LocalAuthentication
import SwiftUI

@main
struct CommonCentsApp: App {
    @State private var model = AppModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .onChange(of: scenePhase) { _, phase in model.sceneChanged(to: phase) }
        }
    }
}

@MainActor @Observable
final class AppModel {
    static let lockAfterSeconds: TimeInterval = 60

    let store: SnapshotStore
    let client: SyncClient
    var snapshot: Snapshot?
    var paired: PairedMac?
    var history: [SyncEvent] = []
    var locked = true
    /// The app-switcher preview is covered whenever the app is not active (PRD §9).
    var obscured = false
    var syncing = false
    var lastError: String?
    var staleThresholdHours = Freshness.defaultThresholdHours
    var defaultView: ViewScope = .household
    var backgroundedAt: Date?
    let demo: Bool

    init() {
        let store = (try? SnapshotStore.applicationSupport())
            ?? SnapshotStore(folder: FileManager.default.temporaryDirectory)
        self.store = store
        client = SyncClient(store: store, keeper: KeychainPairing())
        #if DEBUG
        demo = ProcessInfo.processInfo.arguments.contains("-demo")
        if ProcessInfo.processInfo.arguments.contains("-unlocked") { locked = false }
        #else
        demo = false
        #endif
        reload()
    }

    func reload() {
        snapshot = store.installed() ?? demoSnapshot()
        paired = client.keeper.load()
        history = store.history()
    }

    /// A bundled synthetic snapshot, only in a debug build launched with -demo, and only while
    /// nothing is installed. A release build never shows it.
    func demoSnapshot() -> Snapshot? {
        guard demo, let url = Bundle.main.url(forResource: "demo-snapshot", withExtension: "json"),
              let data = try? Data(contentsOf: url) else { return nil }
        return try? Snapshot.decoded(fromVerified: data)
    }

    func sceneChanged(to phase: ScenePhase) {
        switch phase {
        case .active:
            obscured = false
            if let backgroundedAt, Date().timeIntervalSince(backgroundedAt) >= Self.lockAfterSeconds {
                locked = true
            }
            backgroundedAt = nil
        case .inactive:
            obscured = true
        case .background:
            obscured = true
            backgroundedAt = backgroundedAt ?? Date()
        @unknown default:
            obscured = true
        }
    }

    func unlock() async {
        let context = LAContext()
        context.localizedFallbackTitle = "Use Passcode"
        do {
            if try await context.evaluatePolicy(.deviceOwnerAuthentication,
                                                localizedReason: "Unlock your finances") {
                locked = false
            }
        } catch {
            lastError = "Not unlocked: \(error.localizedDescription)"
        }
    }

    func syncNow() async {
        syncing = true
        defer { syncing = false }
        do {
            snapshot = try await client.syncNow()
            lastError = nil
        } catch {
            lastError = "\(error)"
        }
        history = store.history()
    }

    func pair(_ code: PairingCode, confirm: @escaping @Sendable (String) async -> Bool) async {
        do {
            paired = try await client.pair(code, confirmPrefix: confirm)
            lastError = nil
        } catch {
            lastError = "\(error)"
        }
    }

    func reconnect(_ text: String) {
        do {
            paired = try client.reconnect(text)
        } catch {
            lastError = "\(error)"
        }
    }

    func deleteLocalData() {
        do {
            try client.deleteLocalData()
        } catch {
            lastError = "\(error)"
        }
        reload()
    }
}

enum ViewScope: Hashable {
    case household
    case member(Int)
}

struct RootView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ZStack {
            if model.locked {
                LockView()
            } else {
                MainTabs()
            }
            if model.obscured {
                // Covers the app-switcher preview: nothing financial is visible there.
                Rectangle().fill(.ultraThinMaterial).ignoresSafeArea()
                    .overlay { Image(systemName: "lock.fill").font(.largeTitle).foregroundStyle(.secondary) }
                    .accessibilityHidden(true)
            }
        }
    }
}

struct MainTabs: View {
    @State private var selection = MainTabs.launchTab

    /// A debug build launched with -tab N opens on tab N, for screenshots.
    static var launchTab: Int {
        #if DEBUG
        let arguments = ProcessInfo.processInfo.arguments
        if let index = arguments.firstIndex(of: "-tab"), index + 1 < arguments.count,
           let tab = Int(arguments[index + 1]) { return tab }
        #endif
        return 0
    }

    var body: some View {
        TabView(selection: $selection) {
            Tab("Today", systemImage: "sun.max", value: 0) { NavigationStack { TodayView() } }
            Tab("Spending", systemImage: "chart.bar", value: 1) { NavigationStack { SpendingView() } }
            Tab("Goals", systemImage: "target", value: 2) { NavigationStack { GoalsView() } }
            Tab("Accounts", systemImage: "building.columns", value: 3) { NavigationStack { AccountsView() } }
            Tab("Sync", systemImage: "arrow.triangle.2.circlepath", value: 4) { NavigationStack { SyncView() } }
        }
    }
}

struct LockView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(spacing: 16) {
            Spacer()
            Image(systemName: "lock.shield").font(.system(size: 44)).foregroundStyle(.tint)
                .frame(width: 76, height: 76).background(.background.secondary, in: .rect(cornerRadius: 22))
            Text("CommonCents").font(.title2.bold())
            Text("Locked. Your finances stay on this phone.").foregroundStyle(.secondary)
            Button("Unlock with Face ID") { Task { await model.unlock() } }
                .buttonStyle(.borderedProminent).controlSize(.large)
            if let error = model.lastError { Text(error).font(.footnote).foregroundStyle(.red) }
            Spacer()
            Text("The app-switcher preview is blurred, and the app locks again after 1 minute in the background.")
                .font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center).padding()
        }
        .padding()
    }
}
