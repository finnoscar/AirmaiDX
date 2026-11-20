"""Keep macOS desktop points, physical backing pixels and Wine coordinates distinct."""
import math

def output_size(display,settings):
    bounds=display['CG_frame'];mode=display.get('current_mode',{})
    width=mode.get('pixel_width',bounds['width']);height=mode.get('pixel_height',bounds['height'])
    if not all(isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in (width,height)):
        width,height=bounds['width'],bounds['height']
    if settings['fillDisplay']:return round(width),round(height)
    # Fit in desktop points first; convert the window's content to pixels once.
    visible=display.get('visible_frame',bounds)
    h=min(settings['height']/(height/bounds['height']),max(320,visible['height']-100))
    w=round(h*9/16)
    if w>max(180,visible['width']-64):w=max(180,visible['width']-64);h=round(w*16/9)
    return max(1,round(w*width/bounds['width'])),max(1,round(h*height/bounds['height']))

def match_monitor(displays,target,monitors):
    """Infer Wine's coordinate transform from its primary, never assume 2x or order.

    Wine Retina coordinates can be uniformly doubled even for a display left
    of/above the primary. Use the observed primary rectangle as the anchor and
    require an unambiguous match of all four edges of the selected display.
    """
    primary=next((d for d in displays if d.get('main')),None)
    windows=next((m for m in monitors if m.get('primary')),None)
    if primary is None or windows is None:return None
    p=primary['CG_frame'];w=windows['bounds'];t=target['CG_frame']
    if p['width']<=0 or p['height']<=0:return None
    sx=(w['right']-w['left'])/p['width'];sy=(w['bottom']-w['top'])/p['height']
    if not all(math.isfinite(v) and .25<=v<=4 for v in (sx,sy)):return None
    left=w['left']+(t['x']-p['x'])*sx;top=w['top']+(t['y']-p['y'])*sy
    expected=dict(left=left,top=top,right=left+t['width']*sx,bottom=top+t['height']*sy)
    matches=[m for m in monitors if all(abs(m['bounds'][key]-value)<=2 for key,value in expected.items())]
    return matches[0] if len(matches)==1 else None
