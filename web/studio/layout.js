// Hero-layout inset geometry — ported from ../nw-viz/src/layout.js so the Studio viewport frames
// the SAME composition the committed hero MP4 does: a wide main shot filling the canvas, with three
// EQUAL-SIZED 4:3 cells stacked down the LEFT edge (FPV top, top-down middle, stats bottom).
//
// `layoutInsets` returns BOTTOM-origin rects (WebGL's setViewport/scissor convention) — used by the
// compositor's renderInset passes. `layoutInsetsCss` converts the same rects to TOP-origin CSS px
// for positioning the DOM overlay boxes (borders/labels/HUD) so they track the canvas on resize.

// Bottom-origin cell rects in CSS px (renderInset multiplies by pixelRatio internally). All three
// cells share one size; they tile the full height with equal margins and gaps. `stats` carries no
// WebGL pass — it only positions the DOM HUD box.
export function layoutInsets(W, H) {
  const margin = Math.round(Math.min(W, H) * 0.02);
  const gap = margin;
  const cellH = Math.floor((H - 2 * margin - 2 * gap) / 3);
  const cellW = Math.round(cellH * 4 / 3); // keep the camera insets a comfortable 4:3
  const x = margin;
  return {
    margin,
    // bottom-origin y: top cell highest, bottom cell at the margin.
    fpv: { x, y: margin + 2 * (cellH + gap), w: cellW, h: cellH },
    top: { x, y: margin + (cellH + gap), w: cellW, h: cellH },
    stats: { x, y: margin, w: cellW, h: cellH },
  };
}

// Same three cells as top-origin CSS rects ({left, top, w, h}) for absolutely-positioned DOM boxes.
export function layoutInsetsCss(W, H) {
  const b = layoutInsets(W, H);
  const conv = (r) => ({ left: r.x, top: H - (r.y + r.h), w: r.w, h: r.h });
  return { margin: b.margin, fpv: conv(b.fpv), top: conv(b.top), stats: conv(b.stats) };
}
