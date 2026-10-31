"""Execute the actual Swift setup methods against an in-memory service model.

No StoreKit, Simulator, account, network or production entitlement override is
used. These regressions establish ordering and identity checks, not that the
native StoreKit service accepts the proposed ordering on a cold CI host.
"""
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Tests/EntitlementTests/ProStoreTests.swift"

FIXTURE = r'''
import Foundation

enum Scenario: String {
    case success, staleID, wrongProduct, outsideXcode, unverified, revoked
    case dirtyInitialLedger, dirtyFinalLedger, dirtyFinalEntitlements, stallAfterVerified
}
enum ProductType { case nonConsumable }
enum Environment: String { case xcode, sandbox }
struct Transaction {
    var id: UInt64 = 42
    var productID = "synthetic.pro"
    var productType = ProductType.nonConsumable
    var environment = Environment.xcode
    var appBundleID = "synthetic.app"
    var revocationDate: Date? = nil
    static var currentEntitlements: Entitlements {
        State.events.append("query")
        State.queries += 1
        if !State.purchased {
            State.earlyQuery = true
            return Entitlements(values: [])
        }
        if State.clearedAfterPurchase {
            if State.scenario == .dirtyFinalEntitlements {
                var unrelated = Transaction(); unrelated.productID = "synthetic.unrelated"
                return Entitlements(values: [.verified(unrelated)])
            }
            return Entitlements(values: [])
        }
        var value = Transaction()
        switch State.scenario {
        case .staleID: value.id = 99
        case .wrongProduct: value.productID = "synthetic.unrelated"
        case .outsideXcode: value.environment = .sandbox
        case .revoked: value.revocationDate = Date(timeIntervalSince1970: 0)
        case .unverified: return Entitlements(values: [.unverified(value, FixtureError.failed)])
        default: break
        }
        return Entitlements(values: [.verified(value)])
    }
    func finish() async { State.events.append("finish"); State.finished = true }
}
enum Verification {
    case verified(Transaction)
    case unverified(Transaction, Error)
}
struct Entitlements: AsyncSequence {
    typealias Element = Verification
    let values: [Verification]
    struct AsyncIterator: AsyncIteratorProtocol {
        var values: [Verification]
        mutating func next() async -> Verification? {
            if !values.isEmpty { return values.removeFirst() }
            if State.scenario == .stallAfterVerified {
                return await withCheckedContinuation { (_: CheckedContinuation<Verification?, Never>) in }
            }
            return nil
        }
    }
    func makeAsyncIterator() -> AsyncIterator { AsyncIterator(values: values) }
}
enum State {
    static var scenario = Scenario.success
    static var events: [String] = []
    static var traces: [String] = []
    static var purchased = false
    static var clearedAfterPurchase = false
    static var finished = false
    static var earlyQuery = false
    static var queries = 0
    static var failures = 0
}
enum FixtureError: Error { case failed }
struct Bundle {
    init(for type: AnyClass) {}
    static let main = Bundle(for: NSObject.self)
    var bundleIdentifier: String? { "synthetic.app" }
    func url(forResource: String, withExtension: String) -> URL? {
        URL(fileURLWithPath: "/synthetic/fixture.storekit")
    }
}
enum ProStore { static let productID = "synthetic.pro" }
final class SKTestSession {
    init(contentsOf: URL) throws { State.events.append("init") }
    var disableDialogs = false
    func resetToDefaultState() { State.events.append("reset") }
    func clearTransactions() {
        State.events.append("clear")
        if State.purchased { State.clearedAfterPurchase = true }
    }
    func allTransactions() -> [Int] {
        State.events.append("ledger")
        if State.scenario == .dirtyInitialLedger && !State.purchased { return [1] }
        if State.scenario == .dirtyFinalLedger && State.clearedAfterPurchase { return [1] }
        return []
    }
    func buyProduct(identifier: String) async throws -> Transaction {
        State.events.append("purchase"); State.purchased = true
        return Transaction()
    }
}
enum Task {
    // Keep the original finite polling loop; avoid real sleeping in model tests.
    static func sleep(for duration: Duration) async throws {}
}
func XCTUnwrap<T>(_ value: T?, _ message: String) throws -> T {
    guard let value else { throw FixtureError.failed }; return value
}
func XCTAssertEqual<T: Equatable>(_ a: T, _ b: T) {
    if a != b { State.failures += 1 }
}
func XCTFail(_ message: String) { State.failures += 1 }
final class FirstEntitlementSchedulingProbe {
    init(started: ContinuousClock.Instant, iteratorSequence: Int) {}
    func start() {}
    func disarm() {}
}
@MainActor final class SetupUnderTest {
    var phaseCase = "testCachedEntitlementSurvivesProductNetworkFailure()"
    var phaseStarted = ContinuousClock().now
    var phaseSequence = 0
    static var schedulingProbeClaimed = false
    var schedulingProbe: FirstEntitlementSchedulingProbe?
    func tracePhase(_ phase: String, _ boundary: String) {
        let marker = phase + ":" + boundary
        State.traces.append(marker)
        if State.scenario == .stallAfterVerified {
            FileHandle.standardOutput.write(Data((marker + "\n").utf8))
        }
    }
    // __ACTUAL_METHODS__
    func exercise() async -> Bool {
        do { _ = try await makeSession(); return true }
        catch { return false }
    }
}
@main struct Main {
    @MainActor static func main() async throws {
        State.scenario = Scenario(rawValue: CommandLine.arguments[1])!
        let returned = await SetupUnderTest().exercise()
        let result: [String: Any] = ["returned": returned, "events": State.events, "traces": State.traces,
            "finished": State.finished, "earlyQuery": State.earlyQuery,
            "queries": State.queries, "assertionFailures": State.failures]
        print(String(data: try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys]), encoding: .utf8)!)
    }
}
'''


class NativeStoreKitSetupOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text()
        begin = cls.source.index("    private func makeSession()")
        end = cls.source.index("    private func eventually(", begin)
        cls.methods = cls.source[begin:end]
        cls.directory = tempfile.TemporaryDirectory(prefix="storekit-order-model-")
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        swift = root / "main.swift"
        swift.write_text(FIXTURE.replace("    // __ACTUAL_METHODS__", cls.methods))
        cls.binary = root / "setup-model"
        subprocess.run(["swiftc", "-swift-version", "5", "-parse-as-library",
                        str(swift), "-o", str(cls.binary)], check=True,
                       capture_output=True, timeout=60)

    def exercise(self, scenario):
        result = subprocess.run([str(self.binary), scenario], check=True,
                                capture_output=True, text=True, timeout=5)
        return json.loads(result.stdout)

    def test_first_query_proves_purchase_then_final_empty_before_return(self):
        result = self.exercise("success")
        self.assertTrue(result["returned"])
        self.assertFalse(result["earlyQuery"])
        self.assertEqual(result["assertionFailures"], 0)
        self.assertEqual(result["queries"], 2)
        self.assertEqual(result["events"], ["init", "reset", "clear", "ledger",
                         "purchase", "query", "finish", "clear", "query", "ledger"])

    def test_stale_identity_cannot_satisfy_preflight(self):
        result = self.exercise("staleID")
        self.assertFalse(result["returned"])
        self.assertFalse(result["finished"])
        self.assertEqual(result["queries"], 100)

    def test_wrong_product_cannot_satisfy_preflight(self):
        result = self.exercise("wrongProduct")
        self.assertFalse(result["returned"])
        self.assertFalse(result["finished"])

    def test_non_xcode_and_unverified_results_stop_before_finish(self):
        for scenario in ("outsideXcode", "unverified"):
            with self.subTest(scenario=scenario):
                result = self.exercise(scenario)
                self.assertFalse(result["returned"])
                self.assertFalse(result["finished"])
                self.assertEqual(result["queries"], 1)

    def test_revoked_purchase_cannot_satisfy_preflight(self):
        result = self.exercise("revoked")
        self.assertFalse(result["returned"])
        self.assertFalse(result["finished"])

    def test_dirty_initial_ledger_blocks_purchase_and_query(self):
        result = self.exercise("dirtyInitialLedger")
        self.assertFalse(result["returned"])
        self.assertNotIn("purchase", result["events"])
        self.assertEqual(result["queries"], 0)

    def test_empty_entitlements_cannot_hide_dirty_final_ledger(self):
        result = self.exercise("dirtyFinalLedger")
        self.assertFalse(result["returned"])
        self.assertTrue(result["finished"])
        self.assertEqual(result["queries"], 101)

    def test_unrelated_entitlement_prevents_empty_final_barrier(self):
        result = self.exercise("dirtyFinalEntitlements")
        self.assertFalse(result["returned"])
        self.assertTrue(result["finished"])
        self.assertEqual(result["queries"], 101)

    def test_native_yield_and_completion_are_distinct_fixed_markers(self):
        result = self.exercise("success")
        markers = [v for v in result["traces"] if v.startswith("Transaction.currentEntitlements")]
        self.assertEqual(markers, ["Transaction.currentEntitlements:begin",
                                  "Transaction.currentEntitlements.yield:verified",
                                  "Transaction.currentEntitlements:end",
                                  "Transaction.currentEntitlements:begin",
                                  "Transaction.currentEntitlements:end"])
        failure = self.exercise("unverified")
        markers = [v for v in failure["traces"] if v.startswith("Transaction.currentEntitlements")]
        self.assertEqual(markers, ["Transaction.currentEntitlements:begin",
                                  "Transaction.currentEntitlements.yield:unverified"])
        self.assertFalse(failure["returned"])

    def test_yield_is_observable_when_the_next_iteration_never_completes(self):
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            subprocess.run([str(self.binary), "stallAfterVerified"], capture_output=True,
                           check=True, timeout=2)
        markers = caught.exception.stdout.decode().splitlines()
        self.assertIn("Transaction.currentEntitlements.yield:verified", markers)
        self.assertNotIn("Transaction.currentEntitlements:end", markers)

    def test_all_eight_case_bodies_enter_the_same_checked_setup(self):
        cases = re.findall(r"    func (test\w+)\(\) async throws \{(.*?)(?=\n    (?:func|private|static)|\n\})", self.source, re.S)
        self.assertEqual(len(cases), 8)
        for name, body in cases:
            with self.subTest(case=name):
                self.assertEqual(body.count("let session = try await makeSession()"), 1)
                self.assertIn("defer { clean(session) }", body)
        self.assertIn("matching: purchase, probeFirstIterator: true", self.methods)
        self.assertIn('"scope": "firstPreflightIterator"', self.source)


if __name__ == "__main__":
    unittest.main()
