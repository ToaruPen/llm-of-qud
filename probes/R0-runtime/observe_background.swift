// Read-only observer: records only the target game's activation and window counts.
import AppKit
import CoreGraphics
import Darwin
import Foundation

let target = URL(fileURLWithPath: CommandLine.arguments[1]).standardizedFileURL
let pidFile = URL(fileURLWithPath: CommandLine.arguments[2])
let output = URL(fileURLWithPath: CommandLine.arguments[3])
let duration = CommandLine.arguments.count > 4 ? Double(CommandLine.arguments[4])! : 900
precondition(duration.isFinite && duration > 0 && duration <= 43200)
let deadline = Date().addingTimeInterval(duration)
var targetPID: pid_t?
var activations = 0
var activationTimes: [Double] = []
var firstActiveTime: Double?
var lastActiveTime: Double?
let startedAt = Date().timeIntervalSince1970
var activeSamples = 0
var samples = 0
var maxWindows = 0
var windowQueryFailures = 0
var exited = false
let workspace = NSWorkspace.shared

func matches(_ app: NSRunningApplication) -> Bool {
    app.executableURL?.standardizedFileURL == target || app.processIdentifier == targetPID
}

let observer = workspace.notificationCenter.addObserver(
    forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main
) { notification in
    if let app = notification.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication,
       matches(app) {
        activations += 1
        if activationTimes.count < 100 { activationTimes.append(Date().timeIntervalSince1970) }
    }
}

func save() throws {
    let report: [String: Any] = [
        "pid": targetPID.map { Int($0) } ?? 0,
        "activation_events": activations, "active_samples": activeSamples,
        "samples": samples, "max_onscreen_windows": maxWindows, "exit_observed": exited,
        "window_query_failures": windowQueryFailures,
        "started_unix_s": startedAt, "updated_unix_s": Date().timeIntervalSince1970,
        "activation_unix_s": activationTimes,
        "first_active_unix_s": firstActiveTime as Any? ?? NSNull(),
        "last_active_unix_s": lastActiveTime as Any? ?? NSNull()
    ]
    let data = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
    try data.write(to: output, options: .atomic)
}

try save()
print("observer ready")
fflush(stdout)
while Date() < deadline {
    RunLoop.current.run(until: Date().addingTimeInterval(0.1))
    if targetPID == nil, let text = try? String(contentsOf: pidFile, encoding: .utf8),
       let parsed = pid_t(text.trimmingCharacters(in: .whitespacesAndNewlines)) {
        targetPID = parsed
    }
    guard let pid = targetPID else { continue }
    samples += 1
    if workspace.frontmostApplication?.processIdentifier == pid {
        activeSamples += 1
        let now = Date().timeIntervalSince1970
        if firstActiveTime == nil { firstActiveTime = now }
        lastActiveTime = now
    }
    guard let windows = CGWindowListCopyWindowInfo(.optionOnScreenOnly, kCGNullWindowID) as? [[String: Any]] else {
        windowQueryFailures += 1
        break
    }
    let count = windows.filter { ($0[kCGWindowOwnerPID as String] as? Int32) == pid }.count
    maxWindows = max(maxWindows, count)
    exited = kill(pid, 0) != 0 && errno == ESRCH
    try save()
    if exited { break }
}
workspace.notificationCenter.removeObserver(observer)
try save()
exit(exited && samples > 0 && windowQueryFailures == 0 && activations == 0 && activeSamples == 0 && maxWindows == 0 ? 0 : 2)
