// Prepared helper; run only after the user explicitly authorizes native pointer movement.
// It targets one already identified window, moves without clicking, then restores the pointer.
import Foundation
import AppKit
import CoreGraphics

guard CommandLine.arguments.count == 6,
      let windowID = UInt32(CommandLine.arguments[1]),
      let processID = Int32(CommandLine.arguments[2]),
      let xFraction = Double(CommandLine.arguments[3]),
      let yFraction = Double(CommandLine.arguments[4]),
      let seconds = Double(CommandLine.arguments[5]),
      (0.0...1.0).contains(xFraction), (0.0...1.0).contains(yFraction),
      (0.5...10.0).contains(seconds) else {
    fatalError("Usage: hover_pointer windowID processID localXFraction localYFraction dwellSeconds")
}
guard let rows = CGWindowListCopyWindowInfo(.optionIncludingWindow, windowID) as? [[String: Any]],
      let row = rows.first(where: { ($0[kCGWindowNumber as String] as? UInt32) == windowID }),
      (row[kCGWindowOwnerPID as String] as? Int32) == processID,
      let data = row[kCGWindowBounds as String] as? NSDictionary,
      let bounds = CGRect(dictionaryRepresentation: data),
      let previous = CGEvent(source: nil)?.location else {
    fatalError("The requested game window or pointer could not be identified")
}
func move(_ point: CGPoint) {
    guard let event = CGEvent(mouseEventSource: nil, mouseType: .mouseMoved,
                              mouseCursorPosition: point, mouseButton: .left) else {
        fatalError("Could not create the requested pointer movement")
    }
    event.post(tap: .cghidEventTap)
}
let position = CGPoint(x: bounds.minX + bounds.width * xFraction,
                       y: bounds.minY + bounds.height * yFraction)
let wasFocused = NSWorkspace.shared.frontmostApplication?.processIdentifier == processID
move(position)
Thread.sleep(forTimeInterval: 0.10)
let reached = CGEvent(source: nil)?.location
let pointerReachedTarget = reached.map { hypot($0.x - position.x, $0.y - position.y) <= 1 } ?? false
Thread.sleep(forTimeInterval: seconds)
let focusedWhileHovering = NSWorkspace.shared.frontmostApplication?.processIdentifier == processID
move(previous)
Thread.sleep(forTimeInterval: 0.05)
let restored = CGEvent(source: nil)?.location
let restoredPointer = restored.map { hypot($0.x - previous.x, $0.y - previous.y) <= 1 } ?? false
let report: [String: Any] = ["windowID": windowID, "processID": processID,
    "xFraction": xFraction, "yFraction": yFraction, "dwellSeconds": seconds,
    "gameFocusedBefore": wasFocused, "gameFocusedAtEnd": focusedWhileHovering,
    "eventType": "mouseMoved", "clicks": 0, "restoredPointer": restoredPointer,
    "pointerReachedTarget": pointerReachedTarget, "postEventAccess": CGPreflightPostEventAccess()]
let encoded = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
print(String(data: encoded, encoding: .utf8)!)
if !restoredPointer || !pointerReachedTarget { exit(1) }
