// Binary stars: dragging a listing onto the other sun swaps which field it is placed on.
// Claude's starting sun was locked before the listing appeared; what you do with it is scored when you place it.
import { haptic, toast } from "./util.js";

export async function switchSun(ctx, S, { paint }) {
  const bin = ctx.state.system.binary;
  if (!bin) return paint();
  S.sun = 1 - (S.sun || 0);
  S.phase = "idle"; S.r = 0; S.theta = -Math.PI / 2; S.hot = false; S.pinned = false; S.over = null;
  haptic([12, 30, 12]);
  toast(`Now on ${bin.names[S.sun]}`);
  paint();
}
