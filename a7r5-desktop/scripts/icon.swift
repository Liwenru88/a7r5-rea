import AppKit
let target = CommandLine.arguments[1]
let image = NSImage(size: NSSize(width:1024,height:1024))
image.lockFocus()
NSColor(calibratedRed:0.08,green:0.19,blue:0.21,alpha:1).setFill()
NSBezierPath(roundedRect:NSRect(x:32,y:32,width:960,height:960),xRadius:220,yRadius:220).fill()
NSColor(calibratedRed:0.48,green:0.86,blue:0.80,alpha:1).setStroke()
let ring = NSBezierPath(ovalIn:NSRect(x:178,y:178,width:668,height:668));ring.lineWidth=8;ring.stroke()
let attributes:[NSAttributedString.Key:Any] = [.font:NSFont.systemFont(ofSize:510,weight:.light),.foregroundColor:NSColor(calibratedRed:0.67,green:0.94,blue:0.87,alpha:1)]
let mark = "α" as NSString
let size=mark.size(withAttributes:attributes)
mark.draw(at:NSPoint(x:(1024-size.width)/2,y:(1024-size.height)/2+18),withAttributes:attributes)
image.unlockFocus()
let bitmap=NSBitmapImageRep(data:image.tiffRepresentation!)!
try bitmap.representation(using:.png,properties:[:])!.write(to:URL(fileURLWithPath:target))
