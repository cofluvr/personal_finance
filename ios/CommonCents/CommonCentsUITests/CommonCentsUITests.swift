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

    func testEveryTabOpens() {
        let app = launched(["-demo", "-unlocked"])
        for (tab, title) in [("Spending", "Spending"), ("Goals", "Goals"), ("Accounts", "Accounts"),
                             ("Sync", "Data status"), ("Today", "Today")] {
            app.tabBars.buttons[tab].tap()
            XCTAssertTrue(app.navigationBars[title].waitForExistence(timeout: 5), title)
        }
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
        let first = app.cells.firstMatch
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
