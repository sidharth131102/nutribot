/** The site's ambient background -- mounted once in the root layout, fixed
 *  behind every page. A warm off-white base with a couple of very soft,
 *  slow-drifting pale-lime fields for depth (not a moody dark glow) and a
 *  faint dot-grid for texture. Pages that want it visible must not paint an
 *  opaque background over their own root element -- see app/page.tsx,
 *  app/login/page.tsx, app/profile/page.tsx, which omit `bg-background` on
 *  their outer wrapper for this reason. Dense app screens (chat) keep their
 *  own solid panels; the backdrop shows through only in their negative space.
 */
export default function AuroraBackground() {
  return (
    <div className="fixed inset-0 -z-10 overflow-hidden bg-background" aria-hidden>
      <div
        className="absolute -top-1/4 -right-1/4 w-[60vw] h-[60vw] rounded-full blur-[120px] opacity-[0.16] animate-aurora-a"
        style={{ background: "radial-gradient(circle, #d6f83c 0%, transparent 65%)" }}
      />
      <div
        className="absolute -bottom-1/3 -left-1/4 w-[55vw] h-[55vw] rounded-full blur-[120px] opacity-[0.1] animate-aurora-b"
        style={{ background: "radial-gradient(circle, #ff6b4a 0%, transparent 65%)" }}
      />

      {/* Faint panning dot-grid for technical texture */}
      <div
        className="absolute inset-0 opacity-[0.06] animate-grid-pan"
        style={{ backgroundImage: "radial-gradient(rgba(17,17,17,0.9) 1px, transparent 1px)", backgroundSize: "26px 26px" }}
      />
    </div>
  );
}
