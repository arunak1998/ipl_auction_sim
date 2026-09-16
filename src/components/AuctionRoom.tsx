import { Team, Player } from '../types';
import { Gavel, Users } from 'lucide-react';

/**
 * The auction hall, in 2.5D, sized to fit ONE screen.
 *
 * Depth is faked rather than rendered: desks sit on an arc, and everything
 * further from the camera is drawn smaller and dimmer. That reads as a room
 * without a 3D engine, without assets, and without the stacking-context
 * bugs real CSS `preserve-3d` invites once children need blur and text on
 * top of each other.
 *
 * LAYOUT RULE: this component must never force the page to scroll. A real
 * auction is one room you can see all of at once -- the first version had a
 * min-height that pushed the team desks below the fold, so you could watch
 * the auctioneer or the teams but never both. Everything here is sized in
 * percentages of whatever height the parent gives it.
 */

interface Props {
  teams: Team[];
  userTeamId: string | null;
  currentBidderId: string | null;
  currentPlayer: Player | null;
  currentBid: number;
  lotNumber: number;
  activeSet: string | null;
  auctioneerCall: string | null;
  hammer: { name: string; team: string; price: number } | null;
  onTeamClick: (team: Team) => void;
}

/** Desk positions along an arc. Kept narrow enough that all ten fit. */
function deskLayout(index: number, total: number) {
  const t = total === 1 ? 0 : (index / (total - 1)) * 2 - 1;
  const angle = t * 1.2;
  const depth = Math.cos(angle);              // 1 = nearest, ~0.36 = furthest
  return {
    x: 50 + Math.sin(angle) * 41,             // 9%..91% -- wider, clears the card
    y: 99 - depth * 11,                       // 88%..99% -- hugs the floor
    scale: 0.62 + depth * 0.22,
    depth,
  };
}

export default function AuctionRoom({
  teams, userTeamId, currentBidderId, currentPlayer, currentBid, lotNumber,
  activeSet, auctioneerCall, hammer, onTeamClick,
}: Props) {
  const sold = auctioneerCall === 'SOLD!';
  const unsold = auctioneerCall === 'UNSOLD';
  const calling = !!auctioneerCall && !sold && !unsold;

  const bidderIndex = teams.findIndex(t => t.id === currentBidderId);
  const bidder = bidderIndex >= 0 ? deskLayout(bidderIndex, teams.length) : null;
  const bidderTeam = bidderIndex >= 0 ? teams[bidderIndex] : null;

  // Camera drifts toward the bidder. Small on purpose -- a big swing makes
  // the room feel unstable.
  const camX = bidder ? (50 - bidder.x) * 0.12 : 0;

  // The franchise's REAL colour (MI navy, CSK yellow, RR pink) floods the
  // room while they hold the bid. Broadcasts do this and it is the single
  // clearest way to read "who is winning" without looking at any text.
  const teamColor = bidderTeam?.color ?? '#22d3ee';

  return (
    <div
      className="relative flex-1 min-h-0 rounded-2xl overflow-hidden border bg-[#04060d] transition-colors duration-500"
      style={{ ['--team' as any]: teamColor, borderColor: bidderTeam ? `${teamColor}55` : 'var(--line)' }}
    >
      {/* team-colour wash, strongest right after a raise */}
      <div
        key={`${currentBidderId}-${currentBid}`}
        className="absolute inset-0 pointer-events-none animate-team-flash z-[5]"
        style={{ background: `radial-gradient(ellipse at 50% 100%, ${teamColor}, transparent 62%)` }}
      />
      {/* ---------- hall ---------- */}
      <div className="absolute inset-0">
        <div className="absolute inset-x-0 top-0 h-[45%] bg-gradient-to-b from-slate-900/80 via-[#080c18] to-transparent" />
        <div className="absolute inset-x-0 bottom-0 h-[58%]" style={{ background: 'linear-gradient(to bottom,#070b14,#0b1120 45%,#05070f)' }} />
        <div
          className="absolute inset-x-0 bottom-0 h-[58%] opacity-[0.15]"
          style={{
            backgroundImage:
              'repeating-linear-gradient(to right, rgba(34,211,238,0.5) 0 1px, transparent 1px 90px),' +
              'repeating-linear-gradient(to bottom, rgba(34,211,238,0.35) 0 1px, transparent 1px 56px)',
            maskImage: 'linear-gradient(to bottom, transparent, black 60%)',
            WebkitMaskImage: 'linear-gradient(to bottom, transparent, black 60%)',
            transform: 'perspective(420px) rotateX(60deg)',
            transformOrigin: 'bottom center',
          }}
        />
        <div className="absolute -top-20 left-1/4 w-80 h-80 rounded-full bg-cyan-500/10 blur-[100px]" />
        <div className="absolute -top-20 right-1/4 w-80 h-80 rounded-full bg-indigo-500/10 blur-[100px]" />
      </div>

      <div className="absolute inset-0 transition-transform duration-700 ease-out" style={{ transform: `translateX(${camX}%)` }}>
        {/* ---------- auctioneer: small, at the back ---------- */}
        <div className="absolute left-1/2 top-[3%] -translate-x-1/2 flex flex-col items-center scale-75 origin-top">
          <div className="relative flex flex-col items-center">
            <div className={`w-6 h-6 rounded-full bg-slate-300/90 ${calling ? 'animate-bounce' : ''}`} />
            <div className="w-14 h-10 -mt-1 rounded-t-2xl bg-slate-700 border-x border-t border-slate-500/40" />
            <div
              className="absolute -right-5 top-5 origin-bottom-left transition-transform duration-150"
              style={{ transform: sold ? 'rotate(60deg)' : calling ? 'rotate(-28deg)' : 'rotate(-8deg)' }}
            >
              <div className="w-9 h-1.5 rounded bg-slate-500" />
              <Gavel className={`w-4 h-4 -mt-1 ml-6 ${sold ? 'text-emerald-400' : 'text-amber-400/80'}`} />
            </div>
          </div>
          <div className="w-32 h-10 rounded-t-md bg-gradient-to-b from-slate-800 to-slate-900 border-t border-x border-cyan-500/20 flex items-center justify-center">
            <span className="text-[7px] font-mono font-bold tracking-[0.3em] text-cyan-500/60 uppercase">Auctioneer</span>
          </div>
        </div>

        {/* ---------- THE LOT: the most important thing on screen ---------- */}
        {/* The lot fills the space ABOVE the desk line and centres itself in
            it. It used to be pinned at a fixed top percentage, which meant
            that on a short window the bottom of the card -- the base price,
            the model value, the current bid -- was simply cut off by the
            room's overflow. Centring in a bounded box cannot clip. */}
        <div className="absolute inset-x-0 top-[9%] bottom-[15%] flex items-center justify-center px-3 z-[60] pointer-events-none">
        <div className="relative w-[min(92%,520px)] pointer-events-auto">
          <div
            className={`absolute -top-24 left-1/2 -translate-x-1/2 w-[220%] h-56 pointer-events-none transition-opacity duration-500 ${unsold ? 'opacity-20' : 'opacity-100'}`}
            style={{
              background: sold
                ? 'radial-gradient(ellipse at 50% 0%, rgba(16,185,129,0.25), transparent 70%)'
                : `radial-gradient(ellipse at 50% 0%, ${teamColor}40, transparent 70%)`,
            }}
          />
          {currentPlayer ? (
            <div
              className={`relative rounded-2xl border-2 backdrop-blur-sm transition-all duration-300 overflow-hidden ${
                sold ? 'border-emerald-400/70 bg-emerald-950/50 shadow-[0_0_50px_rgba(16,185,129,0.3)]'
                : unsold ? 'border-slate-700 bg-slate-900/70'
                : 'border-cyan-400/50 bg-slate-950/85 shadow-[0_0_44px_rgba(34,211,238,0.2)]'
              }`}
            >
              {/* lot header */}
              <div className="px-4 py-1.5 bg-slate-950/70 border-b border-slate-800 flex items-center justify-between">
                <span className="text-[9px] font-mono font-bold tracking-[0.25em] text-cyan-500/80 uppercase">
                  {activeSet ? `Set ${activeSet}` : 'Auction'} · Lot {lotNumber}
                </span>
                <span className="text-[9px] font-mono text-slate-500 uppercase tracking-widest">
                  {currentPlayer.status}
                </span>
              </div>

              <div className="px-5 py-3 flex items-center gap-3.5">
                <div className="w-14 h-14 rounded-xl bg-slate-900 border border-slate-700 flex items-center justify-center text-2xl shrink-0">
                  👤
                </div>
                <div className="min-w-0 flex-1">
                  <div className="font-display font-extrabold text-white text-2xl uppercase tracking-tight leading-none truncate">
                    {currentPlayer.name}
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px] font-mono uppercase">
                    <span className="bg-slate-900 border border-slate-700 px-2 py-0.5 rounded text-slate-300">{currentPlayer.role}</span>
                    <span className="bg-slate-900 border border-slate-700 px-2 py-0.5 rounded text-slate-300">{currentPlayer.country || 'India'}</span>
                    <span
                      className={`px-2 py-0.5 rounded border ${
                        currentPlayer.ratingIsReal === false
                          ? 'bg-slate-800/60 border-slate-700 text-slate-500'
                          : 'bg-cyan-500/10 border-cyan-500/30 text-cyan-300'
                      }`}
                      title={currentPlayer.ratingIsReal === false
                        ? 'No measured career record — this is a default rating for an uncapped player'
                        : 'Value score from real ball-by-ball career data'}
                    >
                      ★ {currentPlayer.rating}{currentPlayer.ratingIsReal === false ? '?' : ''}
                    </span>
                  </div>
                </div>
              </div>

              {/* the money */}
              <div className="px-5 py-3 bg-slate-950/60 border-t border-slate-800 flex items-end justify-between gap-3">
                <div className="flex gap-4">
                  <div>
                    <div className="text-[8px] font-mono text-slate-500 uppercase tracking-[0.2em]">Base</div>
                    <div className="font-mono text-sm text-slate-300 leading-none mt-1">{currentPlayer.basePrice.toFixed(2)} Cr</div>
                  </div>
                  {currentPlayer.fairPrice !== undefined && (
                    <div title="What the trained price model predicts this player is worth — it also sets every AI team's ceiling">
                      <div className="text-[8px] font-mono text-cyan-500/70 uppercase tracking-[0.2em]">Model value</div>
                      <div className="font-mono text-sm text-cyan-300 leading-none mt-1">
                        {currentPlayer.fairPrice.toFixed(2)} Cr
                      </div>
                    </div>
                  )}
                  {currentBid > 0 && currentPlayer.fairPrice ? (
                    <div>
                      <div className="text-[8px] font-mono text-slate-500 uppercase tracking-[0.2em]">vs model</div>
                      <div className={`font-mono text-sm leading-none mt-1 font-bold ${
                        currentBid > currentPlayer.fairPrice * 1.15 ? 'text-rose-400'
                        : currentBid < currentPlayer.fairPrice * 0.85 ? 'text-emerald-400'
                        : 'text-slate-300'
                      }`}>
                        {(currentBid / currentPlayer.fairPrice).toFixed(2)}x
                      </div>
                    </div>
                  ) : null}
                </div>
                <div className="text-right">
                  <div className="text-[8px] font-mono text-slate-500 uppercase tracking-[0.2em]">
                    {currentBid === 0 ? 'Awaiting bid' : sold ? 'Sold for' : 'Current bid'}
                  </div>
                  <div
                    key={currentBid}
                    className={`font-mono font-black text-4xl leading-none mt-0.5 animate-tick ${sold ? 'text-emerald-400' : 'money'}`}
                  >
                    {currentBid === 0 ? '—' : `${currentBid.toFixed(2)}`}
                    {currentBid > 0 && <span className="text-lg ml-1 opacity-70">Cr</span>}
                  </div>
                  {bidderTeam && !sold && (
                    <div
                      className="text-[10px] font-mono mt-1 uppercase tracking-wider truncate max-w-[220px] font-bold"
                      style={{ color: teamColor }}
                    >
                      {bidderTeam.name}
                    </div>
                  )}
                </div>
              </div>

              {/* the auctioneer's call, on the card where you are already looking */}
              {auctioneerCall && (
                <div
                  className={`px-5 py-1.5 text-center text-[11px] font-mono font-black tracking-[0.3em] uppercase border-t ${
                    sold ? 'bg-emerald-500/20 border-emerald-400/40 text-emerald-300'
                    : unsold ? 'bg-slate-800/60 border-slate-700 text-slate-400'
                    : 'bg-amber-500/20 border-amber-400/40 text-amber-300 animate-pulse'
                  }`}
                >
                  {auctioneerCall}
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-2xl border-2 border-dashed border-slate-800 px-4 py-8 text-center text-[10px] font-mono uppercase tracking-widest text-slate-600">
              Waiting for the next lot
            </div>
          )}
        </div>
        </div>

        {/* ---------- team desks ---------- */}
        {teams.map((team, i) => {
          const pos = deskLayout(i, teams.length);
          const isBidding = team.id === currentBidderId;
          const isYou = team.id === userTeamId;
          const spent = 125 - team.budget;
          return (
            <button
              key={team.id}
              onClick={() => onTeamClick(team)}
              title={`${team.name} — click to view squad`}
              className="absolute cursor-pointer group"
              style={{
                left: `${pos.x}%`,
                top: `${pos.y}%`,
                transform: `translate(-50%,-100%) scale(${pos.scale})`,
                zIndex: Math.round(pos.depth * 40),
                opacity: 0.6 + pos.depth * 0.4,
              }}
            >
              <div className={`mx-auto w-3.5 origin-bottom ${isBidding ? 'h-8 opacity-100 animate-paddle' : 'h-0 opacity-0'}`}>
                <div
                  className="w-3.5 h-4 rounded-sm border border-white/50"
                  style={{ background: team.color, boxShadow: `0 0 14px ${team.color}` }}
                />
                <div className="w-1 h-4 mx-auto bg-slate-500" />
              </div>
              <div
                className={`px-2 py-1 rounded-md border text-center min-w-[64px] transition-all duration-300 ${
                  isBidding ? '-translate-y-1'
                  : isYou ? 'bg-cyan-500/10 border-cyan-400/60'
                  : 'bg-slate-900/85 border-slate-700 group-hover:border-slate-500'
                }`}
                style={isBidding ? {
                  background: `${team.color}33`,
                  borderColor: team.color,
                  boxShadow: `0 0 22px ${team.color}88`,
                } : undefined}
              >
                <div className={`font-display font-black text-[10px] tracking-wider uppercase leading-none ${
                  isBidding ? 'text-white' : isYou ? 'text-cyan-300' : 'text-slate-300'
                }`}>
                  {team.shortName}
                </div>
                <div className="mt-0.5 font-mono text-[7px] leading-none text-slate-400 flex items-center justify-center gap-0.5">
                  {team.budget.toFixed(0)}<span className="text-slate-600">cr</span>
                  <Users className="w-2 h-2 text-slate-600 ml-0.5" />{team.squad.length}
                </div>
                <div className="mt-0.5 h-0.5 w-full rounded-full bg-slate-800 overflow-hidden">
                  <div
                    className="h-full transition-all duration-500"
                    style={{
                      width: `${Math.min(100, (spent / 125) * 100)}%`,
                      background: isBidding ? team.color : isYou ? '#22d3ee' : '#475569',
                    }}
                  />
                </div>
              </div>
              {isYou && <div className="mt-0.5 text-[6px] font-mono font-bold tracking-[0.2em] text-cyan-500 uppercase">You</div>}
            </button>
          );
        })}
      </div>

      {/* ---------- hammer takeover ---------- */}
      {hammer && (
        <div className="absolute inset-0 z-50 flex items-center justify-center bg-slate-950/85 backdrop-blur-sm animate-scale-up">
          <div className="text-center space-y-1.5 px-6">
            <Gavel className="w-10 h-10 text-emerald-400 mx-auto" />
            <div className="text-[9px] font-mono font-black tracking-[0.35em] text-emerald-400 uppercase">Sold</div>
            <div className="font-display font-extrabold text-2xl text-white uppercase tracking-tight">{hammer.name}</div>
            <div className="text-xs font-mono text-slate-300">to <span className="text-cyan-300 font-bold">{hammer.team}</span></div>
            <div className="text-3xl font-black font-mono text-emerald-400">{hammer.price.toFixed(2)} CR</div>
          </div>
        </div>
      )}
    </div>
  );
}
