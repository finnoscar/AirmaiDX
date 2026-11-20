import AppKit
import CoreGraphics
import Foundation

// Read-only geometry/mode inventory. Does not change modes or collect EDID serials.
var rows:[[String:Any]]=[]
for screen in NSScreen.screens {
    guard let number=screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else {continue}
    let id=CGDirectDisplayID(number.uint32Value)
    let f=screen.frame, v=screen.visibleFrame, b=CGDisplayBounds(id)
    var row:[String:Any] = ["display_id":id,"name":screen.localizedName,"main":id==CGMainDisplayID(),
        "backing_scale":screen.backingScaleFactor,"appkit_frame":["x":f.minX,"y":f.minY,"width":f.width,"height":f.height],
        "visible_frame":["x":v.minX,"y":v.minY,"width":v.width,"height":v.height],
        "CG_frame":["x":b.minX,"y":b.minY,"width":b.width,"height":b.height],
        "pixel_width":CGDisplayPixelsWide(id),"pixel_height":CGDisplayPixelsHigh(id),
        "rotation":CGDisplayRotation(id),"built_in":CGDisplayIsBuiltin(id) != 0,
        "mirrors_display_id":CGDisplayMirrorsDisplay(id)]
    if let uuid=CGDisplayCreateUUIDFromDisplayID(id)?.takeRetainedValue() {
        row["display_uuid"]=CFUUIDCreateString(nil,uuid) as String
    }
    if let m=CGDisplayCopyDisplayMode(id) {
        row["pixel_width"]=m.pixelWidth;row["pixel_height"]=m.pixelHeight
        row["current_mode"]=["width":m.width,"height":m.height,"pixel_width":m.pixelWidth,"pixel_height":m.pixelHeight,"refresh_rate":m.refreshRate]
    }
    if let modes=CGDisplayCopyAllDisplayModes(id,nil) as? [CGDisplayMode] {
        var seen=Set<String>()
        row["available_modes"]=modes.compactMap { m -> [String:Any]? in
            let key="\(m.width)x\(m.height):\(m.pixelWidth)x\(m.pixelHeight):\(m.refreshRate)"
            guard seen.insert(key).inserted else {return nil}
            return ["width":m.width,"height":m.height,"pixel_width":m.pixelWidth,"pixel_height":m.pixelHeight,"refresh_rate":m.refreshRate]
        }
    }
    rows.append(row)
}
let data=try JSONSerialization.data(withJSONObject:rows,options:[.prettyPrinted,.sortedKeys])
FileHandle.standardOutput.write(data)
FileHandle.standardOutput.write(Data("\n".utf8))
