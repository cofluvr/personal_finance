// The app's screens on the simulator with the bundled synthetic snapshot (-demo): the lock shows
// no figure, the stale and new-month states say so, every tab opens, and nothing invites an edit.

import XCTest

@MainActor
final class CommonCentsUITests: XCTestCase {
    override func setUp() async throws {
        continueAfterFailure = false
    }

    func launched(_ arguments: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = arguments
        app.launch()
        return app
    }

    func testTheLockShowsNoFigure() {
        let app = launched(["-demo"])
        XCTAssertTrue(app.buttons["Unlock with Face ID"].waitForExistence(timeout: 10))
        let money = NSPredicate(format: "label CONTAINS '$'")
        XCTAssertEqual(app.staticTexts.matching(money).count, 0)
        XCTAssertFalse(app.tabBars.firstMatch.exists)
    }

    func testAnOldSnapshotIsLabelledNotCurrentAndItsMonth() {
        let app = launched(["-demo", "-unlocked"])
        XCTAssertTrue(app.navigationBars["Today"].waitForExistence(timeout: 10))
        let stale = NSPredicate(format: "label BEGINSWITH 'Snapshot is'")
        XCTAssertTrue(app.staticTexts.matching(stale).firstMatch.exists)
        XCTAssertTrue(app.staticTexts["A new month has started"].exists)
        XCTAssertTrue(app.staticTexts["Not current"].exists)
        XCTAssertFalse(app.staticTexts["Safe to spend today"].exists,
                       "an old snapshot never says today")
    }

    func testAMemberViewShowsTheirBudgetPaceNeverAZero() {
        let app = launched(["-demo", "-unlocked"])
        app.buttons["Alex"].tap()
        XCTAssertTrue(app.staticTexts["Alex's budget pace"].waitForExistence(timeout: 5))
        // The demo plan gives members no part: said so, never shown as $0.00.
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'No part in the plan'"))
            .firstMatch.exists)
        XCTAssertFalse(app.staticTexts["Safe to spend today"].exists)
    }

    func testTheLargestTextStillShowsTheFigure() {
        let app = XCUIApplication()
        app.launchArguments = ["-demo", "-unlocked", "-UIPreferredContentSizeCategoryName",
                               "UICTContentSizeCategoryAccessibilityXXXL"]
        app.launch()
        XCTAssertTrue(app.navigationBars["Today"].waitForExistence(timeout: 10))
        // The banners come first at this size: scroll to the figure, as a person would.
        let figure = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS '$53.57'")).firstMatch
        for _ in 0..<6 where !figure.exists { app.swipeUp() }
        XCTAssertTrue(figure.exists)
    }

    func testEveryTabOpens() {
        let app = launched(["-demo", "-unlocked"])
        for (tab, title) in [("Spending", "Spending"), ("Goals", "Goals"), ("Accounts", "Accounts"),
                             ("Sync", "Data status"), ("Today", "Today")] {
            app.tabBars.buttons[tab].tap()
            XCTAssertTrue(app.navigationBars[title].waitForExistence(timeout: 5), title)
        }
    }

    /// The charts (review of 2026-11-23) reach VoiceOver with the snapshot's own figures.
    func testChartsSpeakTheSnapshotsFigures() {
        let app = launched(["-demo", "-unlocked"])
        XCTAssertTrue(app.navigationBars["Today"].waitForExistence(timeout: 10))
        let labelled = { (label: String) in
            app.descendants(matching: .any).matching(NSPredicate(format: "label == %@", label)).firstMatch
        }
        XCTAssertTrue(labelled("Budget").exists, "the two limits' chart")
        let spent = labelled("Spent, actual")
        for _ in 0..<6 where !spent.exists { app.swipeUp() }
        XCTAssertTrue(spent.exists, "the budget's spent-of-target bar")
        app.tabBars.buttons["Spending"].tap()
        let trend = labelled("Income and spending by month")
        XCTAssertTrue(trend.waitForExistence(timeout: 5), "the monthly trend chart")
        XCTAssertTrue((trend.value as? String ?? "").contains("May: income $2,500.00, spending $0.00"))
        app.tabBars.buttons["Accounts"].tap()
        XCTAssertTrue(labelled("Mortgage").waitForExistence(timeout: 5), "the net worth chart")
        let dues = labelled("Payments due")
        for _ in 0..<6 where !dues.exists { app.swipeUp() }
        XCTAssertTrue((dues.value as? String ?? "").contains("Mon 5 Jan: $1,500.00 due, $0.00 paid, Missed"))
    }

    func testWhyExplainsTheTwoLimits() {
        let app = launched(["-demo", "-unlocked"])
        app.navigationBars["Today"].buttons["Why?"].tap()
        XCTAssertTrue(app.navigationBars["Why this number"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Two limits, the lower wins"].exists
                      || app.staticTexts["TWO LIMITS, THE LOWER WINS"].exists)
    }

    func testATransactionIsReadOnly() {
        let app = launched(["-demo", "-unlocked", "-tab", "1"])
        app.buttons["Transactions, last 90 days"].tap()
        // The first cell is the cash-flow chart: open a transaction by its description.
        let first = app.cells.containing(.staticText, identifier: "SYNTHETIC PAYROLL").firstMatch
        XCTAssertTrue(first.waitForExistence(timeout: 5))
        first.tap()
        XCTAssertTrue(app.staticTexts["To change it, use the Mac. The phone is read-only."]
            .waitForExistence(timeout: 5))
        XCTAssertEqual(app.textFields.count, 0)
    }

    func testSyncWaitsForPairingAndSettingsOfferDeletion() {
        let app = launched(["-demo", "-unlocked", "-tab", "4"])
        XCTAssertTrue(app.staticTexts["Pair this phone with the Mac first, under Settings."]
            .waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["Sync now"].isEnabled)
        app.buttons["Settings"].tap()
        XCTAssertTrue(app.staticTexts["Not paired"].waitForExistence(timeout: 5))
        app.buttons["Delete local data"].tap()
        XCTAssertTrue(app.buttons["Delete"].waitForExistence(timeout: 5))
    }

    func testReturningWithinAMinuteStaysUnlocked() {
        let app = launched(["-demo", "-unlocked"])
        XCTAssertTrue(app.navigationBars["Today"].waitForExistence(timeout: 10))
        XCUIDevice.shared.press(.home)
        app.activate()
        XCTAssertTrue(app.navigationBars["Today"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.buttons["Unlock with Face ID"].exists)
    }
}
