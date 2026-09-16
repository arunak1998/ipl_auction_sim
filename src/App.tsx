import { useState, useEffect, useRef } from 'react';
import { Player, Team, BiddingLog as LogType } from './types';
import { INITIAL_TEAMS } from './data/defaultTeams';
import { useAuctionSocket } from './hooks/useAuctionSocket';
import { useAuctionPlayback, AuctionEvent, PlaybackSpeed } from './hooks/useAuctionPlayback';
import * as sfx from './lib/sound';
import * as voice from './lib/voice';

// Components
import Leaderboard from './components/Leaderboard';
import AuctionRoom from './components/AuctionRoom';
import BiddingLog from './components/BiddingLog';
import SquadModal from './components/SquadModal';
import Confetti from './components/Confetti';

// Icons
import {
  Play, RotateCcw, AlertTriangle,
  CheckCircle, Flame, Users, Coins, Search, PlusCircle, Trophy,
  Volume2, VolumeX, FastForward, Gavel, Mic, MicOff, History, X
} from 'lucide-react';

// --- Frontend team id (branding/strategy, from defaultTeams.ts) <-> backend team_id (real trained agent) ---
const FRONTEND_TO_BACKEND: Record<string, string> = {
  mumbai: 'mi', rajasthan: 'rr', chennai: 'csk', kolkata: 'kkr', delhi: 'dc',
  bengaluru: 'rcb', hyderabad: 'srh', punjab: 'pbks', lucknow: 'lsg', gujarat: 'gt',
};
const BACKEND_TO_FRONTEND: Record<string, string> = Object.fromEntries(
  Object.entries(FRONTEND_TO_BACKEND).map(([fe, be]) => [be, fe])
);

// The auction clock. `bid` paces raises during live bidding; `count` paces
// the going-once/twice/thrice call, which is deliberately SLOWER -- the
// pause before the hammer is where the tension lives, and it is also the
// window in which a rival can still steal the lot.
const COUNT_THRICE = 3;
const CLOCK_MS: Record<PlaybackSpeed, { bid: number; count: number }> = {
  LIVE:    { bid: 1300, count: 1700 },
  FAST:    { bid: 550,  count: 750  },
  INSTANT: { bid: 60,   count: 80   },
};

// How long the room HOLDS before the first bid on a new player, so the
// auctioneer can read him out in full -- "Sunil Narine. All-rounder, West
// Indies. Base price 2 crore." -- before anyone raises a paddle.
//
// This doubles as the gap after a sale: the hammer falls, the sold line is
// announced, and this hold runs before the next player is bid on, instead
// of the two announcements treading on each other.
const LOT_INTRO_MS: Record<PlaybackSpeed, number> = {
  LIVE: 4200, FAST: 1800, INSTANT: 120,
};

const BUDGET_CR = 125.0; // real 2026 purse, matches the backend -- was 100 Cr in the old local-only simulator

// Squad composition, shown between sets so you can see what you still need
// rather than just how many players you have. The minimums mirror the
// backend's squad_rules.py -- a squad short of these has no legal XI, so
// they are real requirements, not suggestions. Fast/Spin has no individual
// minimum (the backend requires specialist BOWLERS, either kind), so it
// shows a count only.
const ROLE_ORDER: Player['role'][] = ['Batsman', 'Wicketkeeper', 'All-Rounder', 'Fast Bowler', 'Spin Bowler'];

/** The REAL legality rules, copied from backend/rl/squad_rules.py. Two of
 *  them span more than one display role, so they cannot be shown as a
 *  per-role minimum: specialist bowlers counts Fast + Spin together, and
 *  bowling options counts bowlers + all-rounders. There is deliberately no
 *  all-rounder minimum -- the backend has none. */
function squadRequirements(squad: { player: Player }[]) {
  const n = (...roles: Player['role'][]) => squad.filter(s => roles.includes(s.player.role)).length;
  return [
    { label: 'Batters',          have: n('Batsman'),                                     min: 4 },
    { label: 'Wicketkeepers',    have: n('Wicketkeeper'),                                min: 1 },
    { label: 'Specialist bowlers', have: n('Fast Bowler', 'Spin Bowler'),                min: 3 },
    { label: 'Bowling options',  have: n('Fast Bowler', 'Spin Bowler', 'All-Rounder'),   min: 5 },
  ];
}

// The backend's 4-role taxonomy (Batter/Bowler/All-rounder/Wicketkeeper) is
// the roster-legality one and is NOT changed here. Fast vs Spin is a
// separate, real field (bowler_subtype, classified from the CSV's Bowling
// Style), so a bowler is labelled by what he actually bowls.
//
// This used to map every bowler to "Fast Bowler" regardless, which is why
// Rashid Khan and Sunil Narine -- both leg/off spin in the source data --
// were announced as fast bowlers.
const ROLE_MAP: Record<string, Player['role']> = {
  Batter: 'Batsman', Bowler: 'Fast Bowler', 'All-rounder': 'All-Rounder', Wicketkeeper: 'Wicketkeeper',
};

function mapRole(backendRole: string, subtype: string | null | undefined): Player['role'] {
  if (backendRole === 'Bowler') {
    // Only claim a style the data actually supports; an unclassified
    // bowler stays generic rather than being guessed as pace.
    if (subtype === 'Spin') return 'Spin Bowler';
    if (subtype === 'Pace') return 'Fast Bowler';
    return 'Fast Bowler';
  }
  return ROLE_MAP[backendRole] ?? 'Batsman';
}

interface BackendPlayer {
  player_id: string; name: string; role: string; country: string; is_overseas: boolean;
  capped: boolean; value_score: number; base_price_cr: number;
  fair_price_cr?: number; value_score_is_real?: boolean; bowler_subtype?: string | null;
}

function mapBackendPlayer(bp: BackendPlayer): Player {
  return {
    id: bp.player_id,
    name: bp.name,
    basePrice: bp.base_price_cr,
    role: mapRole(bp.role, bp.bowler_subtype),
    status: bp.capped ? 'Capped' : 'Uncapped',
    // Value Score (0-100, our real Phase 1 ranking signal) stands in for the
    // old hand-picked 70-99 "rating" scale -- same idea, different source.
    rating: Math.round(bp.value_score),
    isMarquee: bp.value_score >= 80,
    country: bp.country,
    fairPrice: bp.fair_price_cr,
    ratingIsReal: bp.value_score_is_real,
    bowlingStyle: bp.bowler_subtype ?? undefined,
  };
}

function getNextBid(bid: number, basePrice: number): number {
  // Cosmetic preview only (what will the next raise cost) -- must mirror
  // backend/rl/auction_env.py's next_bid() exactly, or the preview lies.
  if (bid === 0) return basePrice;
  if (bid < 2.0) return parseFloat((bid + 0.20).toFixed(2));
  if (bid < 5.0) return parseFloat((bid + 0.50).toFixed(2));
  return parseFloat((bid + 1.00).toFixed(2));
}

type Phase = 'SETUP' | 'SET_SELECTION' | 'AUCTION_STAGE' | 'NOMINATION' | 'BOOST_ROUND' | 'COMPLETED';

export default function App() {
  const { status, lastMessage, sendMessage } = useAuctionSocket();

  const [userTeamId, setUserTeamId] = useState<string | null>(null);
  const [teams, setTeams] = useState<Team[]>(INITIAL_TEAMS.map(t => ({ ...t, budget: BUDGET_CR })));
  const [phase, setPhase] = useState<Phase>('SETUP');

  const [availableSets, setAvailableSets] = useState<string[]>([]);
  const [activeSet, setActiveSet] = useState<string | null>(null);
  const [currentPlayer, setCurrentPlayer] = useState<Player | null>(null);
  const [currentBid, setCurrentBid] = useState<number>(0);
  const [currentBidderId, setCurrentBidderId] = useState<string | null>(null); // frontend id

  const [biddingLogs, setBiddingLogs] = useState<LogType[]>([]);
  const [unsoldPool, setUnsoldPool] = useState<Player[]>([]);
  const [nominatedIds, setNominatedIds] = useState<string[]>([]);

  const [inspectedTeam, setInspectedTeam] = useState<Team | null>(null);
  const [showConfetti, setShowConfetti] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [isAutoPilot, setIsAutoPilot] = useState<boolean>(false);
  // The hammer count. 0 = live bidding, 1/2/3 = going once/twice/thrice.
  // The auction ends a lot when this passes 3 -- nothing else does.
  const [callStage, setCallStage] = useState<number>(0);
  // Proxy bid: the game raises for you up to this, then stops.
  const [autoBidLimit, setAutoBidLimit] = useState<number | null>(null);
  const [sittingOut, setSittingOut] = useState<boolean>(false);

  // --- Auction theatre: the call the auctioneer is making right now, and
  // the hammer flash. Driven entirely by played-back events, never by the
  // state snapshot. ---
  const [auctioneerCall, setAuctioneerCall] = useState<string | null>(null);
  const [hammer, setHammer] = useState<{ name: string; team: string; price: number } | null>(null);
  const [speed, setSpeed] = useState<PlaybackSpeed>('LIVE');
  const [muted, setMutedState] = useState<boolean>(false);
  const [bidPulse, setBidPulse] = useState<number>(0);
  const [voiceOn, setVoiceOn] = useState<boolean>(true);
  const [showHistory, setShowHistory] = useState<boolean>(false);
  const [lotNumber, setLotNumber] = useState<number>(0);

  const autoPilotTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const escalationRef = useRef<number>(0);
  const announcedLotRef = useRef<string | null>(null);
  // Wall-clock instant before which the auction must not bid -- the
  // auctioneer is still reading the player out. See LOT_INTRO_MS.
  const lotIntroUntilRef = useRef<number>(0);
  // True while we are waiting on a reply to an AI_TICK. Only a tick that
  // came back empty advances the hammer count -- any other UPDATE (opening
  // a set, your own bid) must not.
  const awaitingTickRef = useRef<boolean>(false);

  // --- Apply a backend state snapshot onto local display state ---
  const applyStateSnapshot = (state: any) => {
    setPhase(state.phase);
    setAvailableSets(state.available_sets ?? []);
    setActiveSet(state.active_set);
    setCurrentPlayer(state.current_player ? mapBackendPlayer(state.current_player) : null);
    setCurrentBid(state.current_bid ?? 0);
    setCurrentBidderId(state.current_bidder_id ? BACKEND_TO_FRONTEND[state.current_bidder_id] : null);
    setUnsoldPool((state.unsold_pool ?? []).map(mapBackendPlayer));
    setNominatedIds(state.nominated_ids ?? []);

    setTeams(prev => prev.map(t => {
      const backendId = FRONTEND_TO_BACKEND[t.id];
      const bt = state.teams?.[backendId];
      if (!bt) return t;
      return {
        ...t,
        isHuman: t.id === userTeamId,
        budget: bt.budget,
        squad: (bt.squad ?? []).map((sp: any) => ({
          player: mapBackendPlayer(sp),
          buyPrice: sp.buy_price_cr,
        })),
      };
    }));
  };

  // --- Render ONE event of the auction as it is played back ---
  const renderEvent = (event: AuctionEvent) => {
    const teamName = (backendId?: string) => {
      const feId = backendId ? BACKEND_TO_FRONTEND[backendId] ?? backendId : '';
      return teams.find(t => t.id === feId)?.name ?? backendId ?? '';
    };
    const stamp = () => new Date().toLocaleTimeString();
    const key = () => `${Date.now()}-${Math.random()}`;

    switch (event.type) {
      case 'BID': {
        const feId = event.team_id ? BACKEND_TO_FRONTEND[event.team_id] ?? event.team_id : null;
        setCurrentBid(event.amount ?? 0);
        setCurrentBidderId(feId);
        setAuctioneerCall(null);
        setBidPulse(p => p + 1);
        escalationRef.current += 1;
        if (feId === userTeamId) sfx.playMyBid();
        else sfx.playBid(escalationRef.current);
        voice.announceBid(event.amount ?? 0, teamName(event.team_id));
        setBiddingLogs(prev => [...prev, {
          id: key(), teamId: feId ?? '', teamName: teamName(event.team_id),
          amount: event.amount ?? 0, timestamp: stamp(),
        }].slice(-60));
        break;
      }
      case 'SOLD': {
        const name = teamName(event.team_id);
        const price = event.price_cr ?? 0;
        setAuctioneerCall('SOLD!');
        setHammer({ name: event.player_name ?? '', team: name, price });
        setShowConfetti(true);
        sfx.playSold();
        voice.announceSold(event.player_name ?? '', name, price);
        // A genuinely big price deserves a crowd reaction.
        if (price >= 12) setTimeout(() => sfx.playGasp(), 260);
        escalationRef.current = 0;
        setBiddingLogs(prev => [...prev, {
          id: key(), teamId: 'sold',
          teamName: `SOLD: ${event.player_name} to ${name} for ${price.toFixed(2)} Cr!`,
          amount: price, timestamp: stamp(),
        }].slice(-60));
        break;
      }
      case 'UNSOLD':
        setAuctioneerCall('UNSOLD');
        sfx.playUnsold();
        voice.announceUnsold(event.player_name ?? '');
        escalationRef.current = 0;
        setBiddingLogs(prev => [...prev, {
          id: key(), teamId: 'unsold', teamName: `UNSOLD: ${event.player_name}`,
          amount: 0, timestamp: stamp(),
        }].slice(-60));
        break;
      default:
        break;
    }
  };

  // --- A batch has finished performing: the snapshot is the truth ---
  const commitState = (state: any) => {
    setAuctioneerCall(null);
    setHammer(null);
    escalationRef.current = 0;
    applyStateSnapshot(state);
    const next = state?.current_player;
    // Announce a lot exactly ONCE. commitState runs after every batch, so
    // keying off "a player exists" re-read the full name and base price
    // every time you passed or raised -- which is nothing like an auction.
    if (next && next.player_id !== announcedLotRef.current) {
      announcedLotRef.current = next.player_id;
      // Hold the bidding until he has been read out in full.
      lotIntroUntilRef.current = Date.now() + LOT_INTRO_MS[speed];
      sfx.playNextLot();
      setLotNumber(n => {
        const lot = n + 1;
        voice.announceLot({
          setName: state.active_set ?? null,
          lotNumber: lot,
          name: next.name,
          role: mapRole(next.role, next.bowler_subtype),
          country: next.country || 'India',
          basePrice: next.base_price_cr,
        });
        return lot;
      });
    }
  };

  const { enqueue, skip, isPlaying } = useAuctionPlayback<any>({
    onEvent: renderEvent,
    onBatchComplete: commitState,
    speed,
  });

  // --- Handle every message from the backend ---
  useEffect(() => {
    if (!lastMessage) return;

    if (lastMessage.type === 'ERROR') {
      alert((lastMessage.payload as any)?.message ?? 'Unknown backend error');
      return;
    }
    if (lastMessage.type === 'AUCTION_STARTED' || lastMessage.type === 'UPDATE') {
      const { events, state } = lastMessage.payload as { events: any[]; state: any };

      // The hammer count. A raise -- from anyone, including a late cut-in
      // -- puts the count back to zero, exactly as a real auctioneer
      // restarts it. Silence advances it toward the hammer.
      const raised = (events ?? []).some(e => e.type === 'BID');
      const settled = (events ?? []).some(e => e.type === 'SOLD' || e.type === 'UNSOLD');
      const wasTick = awaitingTickRef.current;
      awaitingTickRef.current = false;

      if (raised || settled) setCallStage(0);
      else if (wasTick && state?.current_player) {
        // A tick nobody answered. This is the only thing that advances the
        // count -- including on a lot at 0 with no bidder at all, which is
        // how an unwanted player reaches UNSOLD instead of hanging forever.
        setCallStage(s => s + 1);
      }
      if (settled) { setAutoBidLimit(null); setSittingOut(false); }

      // Queued, not applied: the batch is performed one beat at a time.
      enqueue({ events: (events ?? []).filter(e => ['BID', 'SOLD', 'UNSOLD'].includes(e.type)), state });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastMessage]);

  // Voices load asynchronously in Chrome; ask for them up front.
  useEffect(() => { voice.initVoice(); }, []);

  // --- Confetti auto-hide ---
  useEffect(() => {
    if (showConfetti) {
      const timer = setTimeout(() => setShowConfetti(false), 2200);
      return () => clearTimeout(timer);
    }
  }, [showConfetti]);

  // --- Setup ---
  const handleSelectTeam = (teamId: string) => setUserTeamId(teamId);

  const handleStartGame = () => {
    if (!userTeamId) {
      alert('Please select an IPL franchise to manage!');
      return;
    }
    if (status !== 'OPEN') {
      alert('Not connected to the auction backend yet -- please wait a moment and try again.');
      return;
    }
    setBiddingLogs([]);
    sendMessage('START_AUCTION', { team_id: FRONTEND_TO_BACKEND[userTeamId] });
  };

  // --- Set selection / bidding ---
  const handleOpenSet = (setName: string) => sendMessage('OPEN_SET', { set_name: setName });
  const handleRaisePaddle = () => sendMessage('PLACE_BID', {});
  const handlePass = () => sendMessage('PASS', {});

  // Skip = take no further part in THIS lot. The clock keeps running and
  // the AI teams finish it between themselves.
  const handleSitOut = () => {
    setSittingOut(true);
    setAutoBidLimit(null);
    sendMessage('SIT_OUT', {});
  };

  // Auto-bid = a proxy instruction. The room raises for you up to your
  // ceiling and stops there, exactly like leaving a limit with an agent.
  const handleAutoBid = () => {
    if (autoBidLimit !== null) {
      setAutoBidLimit(null);
      sendMessage('SET_AUTO_BID', { limit_cr: null });
      return;
    }
    const suggested = currentPlayer?.fairPrice ?? getNextBid(currentBid, currentPlayer?.basePrice ?? 0);
    const entered = window.prompt('Auto-bid up to how many Crore?', suggested.toFixed(2));
    if (entered === null) return;
    const limit = parseFloat(entered);
    if (!isFinite(limit) || limit <= 0) return;
    setAutoBidLimit(limit);
    setSittingOut(false);
    sendMessage('SET_AUTO_BID', { limit_cr: limit });
  };
  // Settles the current lot server-side in one go, instead of answering
  // every increment. The skip button is the only thing that does this.
  const handleResolveLot = () => sendMessage('RESOLVE_LOT', {});

  // --- Nomination / boost round ---
  const handleToggleNomination = (playerId: string) => sendMessage('TOGGLE_NOMINATION', { player_id: playerId });
  const handleLaunchBoostRound = () => sendMessage('LAUNCH_BOOST_ROUND', {});

  // --- The auction clock -------------------------------------------------
  //
  // This is what makes the room an AUCTION rather than a questionnaire. It
  // used to be that nothing moved until you clicked: the AI could only
  // raise inside your own pass/bid request, so the lot sat frozen waiting
  // on you and a pass ended it instantly.
  //
  // Now a timer drives it. Each beat asks the backend for the next raise.
  // Silence advances the hammer count; once it passes THRICE the lot is
  // settled. You are simply another bidder in the room -- if you say
  // nothing, the auction carries on without you.
  useEffect(() => {
    if (!currentPlayer || isPlaying) return;
    if (phase !== 'AUCTION_STAGE' && phase !== 'BOOST_ROUND') return;

    const beat = CLOCK_MS[speed];
    // Hold the room until the player has been read out in full. Without
    // this the first AI raise lands on top of his own name.
    const introLeft = Math.max(0, lotIntroUntilRef.current - Date.now());
    const delay = Math.max(callStage > 0 ? beat.count : beat.bid, introLeft);

    const timer = setTimeout(() => {
      if (callStage > COUNT_THRICE) {
        sendMessage('SETTLE_LOT', {});
      } else {
        // Outsiders may only cut in while the hammer is coming down.
        awaitingTickRef.current = true;
        sendMessage('AI_TICK', { final_call: callStage > 0 });
      }
    }, delay);

    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPlayer?.id, currentBid, currentBidderId, callStage, isPlaying, phase, speed]);

  // "Going once... going twice..." -- spoken as the count advances, so the
  // timing you hear is the timing that is actually running.
  useEffect(() => {
    if (callStage < 1 || callStage > COUNT_THRICE) {
      setAuctioneerCall(null);
      return;
    }
    setAuctioneerCall(['GOING ONCE...', 'GOING TWICE...', 'GOING THRICE...'][callStage - 1]);
    sfx.playGoing(callStage >= 2);
    voice.announceGoing(callStage);
  }, [callStage]);

  // Autopilot now means "never bid for me" rather than "click pass for me":
  // the clock already keeps the room moving.
  useEffect(() => {
    if (!isAutoPilot || !currentPlayer) return;
    if (phase !== 'AUCTION_STAGE' && phase !== 'BOOST_ROUND') return;
    if (sittingOut) return;
    sendMessage('SIT_OUT', {});
    setSittingOut(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAutoPilot, currentPlayer?.id, phase, sittingOut]);

  const handleResetGame = () => {
    setUserTeamId(null);
    setTeams(INITIAL_TEAMS.map(t => ({ ...t, budget: BUDGET_CR })));
    setPhase('SETUP');
    setAvailableSets([]);
    setActiveSet(null);
    setCurrentPlayer(null);
    setCurrentBid(0);
    setCurrentBidderId(null);
    setBiddingLogs([]);
    setUnsoldPool([]);
    setNominatedIds([]);
    setInspectedTeam(null);
    setIsAutoPilot(false);
  };

  // --- Stats and Awards for Completed Screen ---
  const getCompletedStats = () => {
    const evaluatedTeams = teams.map(t => {
      const totalRating = t.squad.reduce((sum, b) => sum + b.player.rating, 0);
      const avgRating = t.squad.length > 0 ? totalRating / t.squad.length : 0;
      const spent = parseFloat((BUDGET_CR - t.budget).toFixed(2));
      return { team: t, totalRating, avgRating: avgRating.toFixed(1), spent };
    });
    const sortedByRosterPower = [...evaluatedTeams].sort((a, b) => b.totalRating - a.totalRating);
    const champion = sortedByRosterPower[0];

    let costliestBuy: { player: Player; teamName: string; price: number } | null = null;
    let valueSteal: { player: Player; teamName: string; price: number } | null = null;
    teams.forEach(t => {
      t.squad.forEach(b => {
        if (!costliestBuy || b.buyPrice > costliestBuy.price) {
          costliestBuy = { player: b.player, teamName: t.name, price: b.buyPrice };
        }
        const valueScore = b.player.rating - b.buyPrice * 2.5;
        if (!valueSteal || valueScore > (valueSteal.player.rating - valueSteal.price * 2.5)) {
          valueSteal = { player: b.player, teamName: t.name, price: b.buyPrice };
        }
      });
    });

    return { champion, costliestBuy, valueSteal, sortedByRosterPower };
  };

  const finalStats = phase === 'COMPLETED' ? getCompletedStats() : null;
  const filteredStandings = finalStats
    ? finalStats.sortedByRosterPower.filter(row => row.team.name.toLowerCase().includes(searchQuery.toLowerCase()))
    : [];

  // Only the auction room is locked to one screen; every other phase needs
  // to scroll (the setup page alone is ten franchise cards tall).
  const inAuction = phase === 'AUCTION_STAGE' || phase === 'BOOST_ROUND';
  const isMyBid = currentBidderId === userTeamId;
  // You cannot bid while the room is still performing the previous war --
  // the player on screen may already be sold on the server.
  const paddleLocked = isMyBid || isPlaying;

  return (
    <div className={`${
      inAuction ? 'h-screen max-h-screen overflow-hidden' : 'min-h-screen overflow-y-auto'
    } bg-[#020617] text-slate-100 font-sans selection:bg-cyan-500 selection:text-slate-950 flex flex-col relative`}>
      <div className="absolute inset-0 overflow-hidden opacity-10 pointer-events-none">
        <div className="absolute -top-24 -left-24 w-96 h-96 bg-cyan-500 rounded-full blur-[120px]"></div>
        <div className="absolute -bottom-24 -right-24 w-96 h-96 bg-rose-500 rounded-full blur-[120px]"></div>
      </div>

      {showConfetti && <Confetti />}

      {/* --- MASTER HEADER --- */}
      <header className="h-16 bg-slate-900 border-b border-cyan-500/30 sticky top-0 z-40 flex items-center justify-between px-6 shrink-0 backdrop-blur-md">
        <div className="flex items-center gap-4">
          <div className="bg-cyan-500 text-slate-950 px-3 py-1 font-black text-xl italic skew-x-[-12deg]">
            IPL 2026
          </div>
          <div className="h-6 w-px bg-slate-700"></div>
          <div className="text-cyan-400 font-display font-extrabold tracking-tighter uppercase flex items-center gap-2 text-sm md:text-base">
            Auction Simulator
            <span className={`ml-2 text-[10px] font-mono normal-case tracking-normal px-2 py-0.5 rounded border ${status === 'OPEN' ? 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10' : 'text-amber-400 border-amber-500/30 bg-amber-500/10 animate-pulse'}`}>
              {status === 'OPEN' ? '● BACKEND CONNECTED' : status === 'CONNECTING' ? '○ CONNECTING...' : '○ DISCONNECTED'}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-6">
          {phase !== 'SETUP' && (
            <div className="hidden md:flex gap-8 text-xs font-semibold uppercase tracking-wider">
              <div className="flex flex-col items-end leading-none">
                <span className="text-slate-500 text-[9px] uppercase tracking-widest font-bold">Phase</span>
                <span className="text-cyan-300 mt-1">{phase.replace('_', ' ')}</span>
              </div>
              {activeSet && (
                <div className="flex flex-col items-end leading-none">
                  <span className="text-slate-500 text-[9px] uppercase tracking-widest font-bold">Active Set</span>
                  <span className="text-cyan-300 mt-1">{activeSet}</span>
                </div>
              )}
            </div>
          )}
          {phase !== 'SETUP' && (
            <button
              onClick={handleResetGame}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-slate-900 hover:bg-slate-800 border border-cyan-500/20 hover:border-cyan-500/50 text-[11px] font-bold text-cyan-300 uppercase tracking-widest transition-all cursor-pointer"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Reset Engine
            </button>
          )}
        </div>
      </header>

      <main className={`flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex flex-col relative z-10 ${
        inAuction ? 'min-h-0 overflow-hidden' : ''
      }`}>

        {/* ================= PHASE 1: SETUP ================= */}
        {phase === 'SETUP' && (
          <div className="flex-1 flex flex-col gap-8 animate-fade-in">
            <div className="text-center max-w-2xl mx-auto space-y-3 py-6">
              <span className="text-cyan-400 font-mono text-xs font-bold bg-cyan-950/40 border border-cyan-500/30 px-3 py-1 rounded uppercase tracking-widest">
                VIVO IPL MOCK AUCTION 2026
              </span>
              <h2 className="text-3xl md:text-4xl font-display font-extrabold text-white tracking-tight leading-none uppercase">
                Championships are Built in the Auction Room
              </h2>
              <p className="text-slate-400 text-xs md:text-sm leading-relaxed">
                Take the hotseat. Choose your IPL team and build a 20-player match-winning roster with a strict {BUDGET_CR} Crore budget.
                Compete against 9 real franchises, each bid by its own trained AI agent -- not a scripted formula.
              </p>
            </div>

            <div className="space-y-4">
              <h3 className="font-display font-extrabold text-xs uppercase tracking-widest text-cyan-400 flex items-center gap-2">
                <span className="w-1.5 h-3 bg-cyan-500 rounded-sm"></span>
                Select Your Franchise
              </h3>
              {/* Horizontal franchise rail. Picking a team pulls it forward
                  and pushes the rest back, so the screen commits to your
                  choice instead of showing ten equal options forever. */}
              <div className="relative -mx-4 px-4">
                <div className="flex gap-4 overflow-x-auto pb-4 snap-x snap-mandatory scrollbar-thin">
                  {teams.map((t) => {
                    const isSelected = userTeamId === t.id;
                    const dimmed = userTeamId !== null && !isSelected;
                    return (
                      <button
                        key={t.id}
                        onClick={() => handleSelectTeam(t.id)}
                        className={`relative snap-center shrink-0 border-2 rounded-2xl p-5 text-left transition-all duration-500 overflow-hidden flex flex-col justify-between group cursor-pointer ${
                          isSelected
                            ? 'w-[320px] h-[230px] border-cyan-400 bg-cyan-950/25 ring-2 ring-cyan-500/25 shadow-[0_0_40px_rgba(34,211,238,0.2)] scale-100'
                            : dimmed
                              ? 'w-[190px] h-[200px] border-slate-800 bg-slate-900/40 opacity-35 hover:opacity-70 scale-95'
                              : 'w-[230px] h-[210px] border-slate-800 hover:border-cyan-500/40 bg-slate-900/60'
                        }`}
                      >
                        <div className={`absolute -top-6 -right-6 w-32 h-32 rounded-full blur-2xl transition-opacity duration-500 ${t.logo} ${isSelected ? 'opacity-25' : 'opacity-10 group-hover:opacity-20'}`} />

                        <div className="flex items-start justify-between relative z-10">
                          <div className={`rounded-lg flex items-center justify-center text-slate-950 font-black skew-x-[-6deg] shadow-lg border border-white/10 transition-all duration-500 ${t.logo} ${
                            isSelected ? 'w-16 h-16 text-lg' : 'w-11 h-11 text-xs'
                          }`}>
                            {t.shortName}
                          </div>
                          {isSelected && (
                            <span className="bg-cyan-500 text-slate-950 text-[9px] font-black px-2.5 py-1 rounded uppercase tracking-widest font-mono">
                              Your Team
                            </span>
                          )}
                        </div>

                        <div className="relative z-10">
                          <p className={`font-display font-extrabold uppercase tracking-tight transition-colors ${
                            isSelected ? 'text-cyan-300 text-lg' : 'text-white text-sm group-hover:text-cyan-400'
                          }`}>
                            {t.name}
                          </p>
                          <p className={`text-slate-400 mt-1.5 leading-snug ${isSelected ? 'text-[11px] line-clamp-3' : 'text-[10px] line-clamp-2'}`}>
                            {t.strategy.description}
                          </p>
                          {isSelected && (
                            <div className="mt-3 flex items-center gap-3 text-[9px] font-mono uppercase tracking-widest text-slate-500">
                              <span>{BUDGET_CR} Cr purse</span>
                              <span className="text-slate-700">|</span>
                              <span>20 slots</span>
                            </div>
                          )}
                        </div>
                      </button>
                    );
                  })}
                </div>
                <div className="text-[9px] font-mono uppercase tracking-widest text-slate-600 mt-1">
                  Scroll sideways to see all ten franchises
                </div>
              </div>
            </div>

            <div className="flex justify-center pt-2 pb-8">
              <button
                onClick={handleStartGame}
                disabled={!userTeamId}
                className={`flex items-center gap-2.5 px-10 py-4 rounded-xl text-xs font-black uppercase tracking-widest transition-all duration-300 shadow-xl cursor-pointer ${
                  userTeamId ? 'bg-cyan-500 hover:bg-cyan-400 text-slate-950 scale-100 hover:scale-[1.02] active:scale-95 shadow-[0_0_20px_rgba(34,211,238,0.3)]' : 'bg-slate-800 text-slate-500 cursor-not-allowed opacity-60'
                }`}
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                LAUNCH AUCTION ARENA
              </button>
            </div>
          </div>
        )}

        {/* ================= PHASE 2: SET SELECTION ================= */}
        {phase === 'SET_SELECTION' && (
          <div className="flex-1 flex flex-col gap-6 max-w-4xl mx-auto w-full animate-fade-in">
            <div className="text-center space-y-2 py-4">
              <span className="text-cyan-400 font-mono text-xs font-bold bg-cyan-950/40 border border-cyan-500/30 px-3 py-1 rounded uppercase tracking-widest">STAGE SELECTION</span>
              <h2 className="text-2xl font-display font-extrabold text-white uppercase">Select Next Auction Set</h2>
              <p className="text-slate-400 text-xs">Franchises will enter bidding set by set. Choose which players to auction next.</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div className="space-y-3">
                <h3 className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest font-mono">Available Sets ({availableSets.length})</h3>
                <div className="space-y-2.5 max-h-[500px] overflow-y-auto custom-scrollbar pr-1">
                  {availableSets.map((setName) => (
                    <button
                      key={setName}
                      onClick={() => handleOpenSet(setName)}
                      className="w-full text-left p-3.5 rounded-xl border flex items-center justify-between transition-all bg-slate-900/50 hover:bg-slate-800/80 border-cyan-500/20 hover:border-cyan-400 hover:scale-[1.01] active:scale-[0.99] cursor-pointer text-slate-100 shadow-[0_0_15px_rgba(34,211,238,0.02)]"
                    >
                      <div className="flex items-center gap-3">
                        <span className="text-xl">{setName.toUpperCase().startsWith('M') ? '💎' : '🏏'}</span>
                        <span className="font-bold text-xs uppercase tracking-wider">Set {setName}</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="bg-slate-950/80 border border-cyan-500/20 shadow-[0_0_30px_rgba(6,182,212,0.05)] rounded-2xl p-5 flex flex-col justify-between">
                <div>
                  <h3 className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest font-mono mb-4">Your Franchise</h3>
                  {(() => {
                    const myTeam = teams.find(t => t.id === userTeamId);
                    if (!myTeam) return null;
                    return (
                      <div className="space-y-5">
                        <div className="flex items-center gap-3">
                          <div className={`w-12 h-12 rounded flex items-center justify-center text-slate-950 font-black text-lg skew-x-[-6deg] shadow-lg border border-white/10 ${myTeam.logo}`}>{myTeam.shortName}</div>
                          <div>
                            <h4 className="font-bold text-white text-base uppercase tracking-tight">{myTeam.name}</h4>
                            <p className="text-[10px] text-slate-500 font-mono uppercase tracking-wider mt-0.5">{myTeam.strategy.name} Style</p>
                          </div>
                        </div>
                        <div className="grid grid-cols-2 gap-3 pt-2 font-mono">
                          <div className="bg-slate-900/40 p-3 rounded-xl border border-cyan-500/10">
                            <span className="text-[9px] text-slate-500 block uppercase tracking-wider">REMAINING PURSE</span>
                            <span className="text-cyan-400 font-black text-sm flex items-center gap-1 mt-1"><Coins className="w-4 h-4 text-cyan-400" />{myTeam.budget.toFixed(2)} CR</span>
                          </div>
                          <div className="bg-slate-900/40 p-3 rounded-xl border border-cyan-500/10">
                            <span className="text-[9px] text-slate-500 block uppercase tracking-wider">SQUAD SIZE</span>
                            <span className="text-cyan-300 font-black text-sm flex items-center gap-1 mt-1"><Users className="w-4 h-4 text-cyan-300" />{myTeam.squad.length} / 20</span>
                          </div>
                        </div>
                      </div>
                    );
                  })()}
                </div>
                {/* Your roster BY ROLE. Between sets is exactly when you
                    decide what to chase next, and "squad size 7/20" does
                    not answer that -- "no keeper, one spinner" does. */}
                {(() => {
                  const myTeam = teams.find(t => t.id === userTeamId);
                  if (!myTeam) return null;
                  return (
                    <div className="mt-5 pt-4 border-t border-cyan-500/10 space-y-2">
                      <h3 className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest font-mono mb-2">Squad by role</h3>
                      <div className="max-h-[210px] overflow-y-auto custom-scrollbar pr-1 space-y-2">
                        {ROLE_ORDER.map(role => {
                          const inRole = myTeam.squad.filter(sp => sp.player.role === role);
                          return (
                            <div key={role}>
                              <div className="flex items-center justify-between">
                                <span className="text-[9px] font-bold uppercase tracking-widest font-mono text-slate-400">
                                  {role}
                                </span>
                                <span className="text-[9px] font-mono font-bold text-slate-500">
                                  {inRole.length}
                                </span>
                              </div>
                              {inRole.length === 0 ? (
                                <p className="text-[10px] text-slate-600 italic mt-0.5">none signed</p>
                              ) : (
                                <div className="flex flex-wrap gap-1 mt-1">
                                  {inRole.map(sp => (
                                    <span key={sp.player.id} className="text-[9px] font-mono bg-slate-900 border border-slate-800 rounded px-1.5 py-0.5 text-slate-300">
                                      {sp.player.name} <span className="text-cyan-500/80">{sp.buyPrice.toFixed(1)}</span>
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>

                      {/* The rules that actually decide whether this squad
                          can field a legal XI. */}
                      <div className="pt-3 mt-1 border-t border-cyan-500/10 space-y-1">
                        {squadRequirements(myTeam.squad).map(req => {
                          const ok = req.have >= req.min;
                          return (
                            <div key={req.label} className="flex items-center justify-between">
                              <span className={`text-[9px] font-mono uppercase tracking-wider ${ok ? 'text-slate-500' : 'text-amber-400'}`}>
                                {ok ? '\u2713' : '\u25cb'} {req.label}
                              </span>
                              <span className={`text-[9px] font-mono font-bold ${ok ? 'text-emerald-400/80' : 'text-amber-400'}`}>
                                {req.have} / {req.min}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}

                <div className="pt-5 border-t border-cyan-500/10 mt-6 text-slate-400 text-[11px] leading-relaxed flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 text-cyan-400 shrink-0" />
                  <span>Each team is strictly required to sign exactly <strong>20 players</strong> total.</span>
                </div>
              </div>
            </div>

            {/* Every franchise, always reachable. Click one to read its full
                squad -- you should never have to wait for a lot to be live
                to see what a rival has built. */}
            <div className="space-y-2">
              <h3 className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest font-mono">All franchises — click to view squad</h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
                {teams.map(team => {
                  const isYou = team.id === userTeamId;
                  return (
                    <button
                      key={team.id}
                      onClick={() => setInspectedTeam(team)}
                      className={`text-left p-2.5 rounded-lg border transition-all cursor-pointer hover:scale-[1.02] ${
                        isYou ? 'bg-cyan-500/10 border-cyan-500/40' : 'bg-slate-900/60 border-slate-800 hover:border-slate-700'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <div className={`w-7 h-7 rounded flex items-center justify-center text-slate-950 font-black text-[10px] skew-x-[-6deg] ${team.logo}`}>
                          {team.shortName}
                        </div>
                        <div className="min-w-0">
                          <p className="text-[10px] font-bold text-slate-200 truncate">{team.shortName}</p>
                          <p className="text-[9px] font-mono text-slate-500">{team.squad.length}/20</p>
                        </div>
                      </div>
                      <p className="text-[9px] font-mono text-cyan-400/90 mt-1.5">{team.budget.toFixed(1)} Cr left</p>
                    </button>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* ================= PHASE 3: AUCTION / BOOST ROUND ================= */}
        {(phase === 'AUCTION_STAGE' || phase === 'BOOST_ROUND') && (
          <div className="flex-1 flex flex-col gap-3 min-h-0 animate-scale-up">
            <div className="flex-1 flex flex-col gap-3 min-h-0">
              <div className="bg-slate-900 border border-cyan-500/20 shadow-[0_0_15px_rgba(6,182,212,0.03)] rounded-xl px-4 py-3 flex items-center justify-between">
                <div>
                  <span className="text-[10px] text-cyan-400 font-mono font-bold tracking-widest uppercase block">
                    {phase === 'BOOST_ROUND' ? 'ACCELERATED BOOST AUCTION (50% OFF)' : `SET ${activeSet}`}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => { const next = !muted; setMutedState(next); sfx.setMuted(next); }}
                    title={muted ? 'Unmute auction room' : 'Mute auction room'}
                    className={`p-1.5 rounded border transition-all cursor-pointer ${
                      muted ? 'bg-slate-950 border-slate-800 text-slate-600' : 'bg-cyan-500/10 border-cyan-500/30 text-cyan-400'
                    }`}
                  >
                    {muted ? <VolumeX className="w-3.5 h-3.5" /> : <Volume2 className="w-3.5 h-3.5" />}
                  </button>
                  <div className="flex rounded border border-slate-800 overflow-hidden">
                    {(['LIVE', 'FAST', 'INSTANT'] as PlaybackSpeed[]).map(s => (
                      <button
                        key={s}
                        onClick={() => setSpeed(s)}
                        title="How fast the auction is performed"
                        className={`px-2 py-1 text-[9px] font-mono font-bold tracking-widest uppercase transition-all cursor-pointer ${
                          speed === s ? 'bg-cyan-500 text-slate-950' : 'bg-slate-950 text-slate-500 hover:text-slate-300'
                        }`}
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                  <button
                    onClick={() => { const n = !voiceOn; setVoiceOn(n); voice.setVoiceEnabled(n); }}
                    title={voiceOn ? 'Mute the auctioneer' : 'Unmute the auctioneer'}
                    className={`p-1.5 rounded border transition-all cursor-pointer ${
                      voiceOn ? 'bg-amber-500/10 border-amber-500/40 text-amber-400' : 'bg-slate-950 border-slate-800 text-slate-600'
                    }`}
                  >
                    {voiceOn ? <Mic className="w-3.5 h-3.5" /> : <MicOff className="w-3.5 h-3.5" />}
                  </button>
                  <button
                    onClick={() => setShowHistory(true)}
                    title="Bidding history"
                    className="p-1.5 rounded border border-slate-700 bg-slate-950 text-slate-400 hover:text-slate-200 transition-all cursor-pointer"
                  >
                    <History className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => { skip(); handleResolveLot(); }}
                    title="Fast-forward: settle this player now"
                    className="p-1.5 rounded border border-amber-500/40 bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 transition-all cursor-pointer"
                  >
                    <FastForward className="w-3.5 h-3.5" />
                  </button>
                <button
                  onClick={() => setIsAutoPilot(!isAutoPilot)}
                  className={`text-[10px] uppercase tracking-widest px-3 py-1.5 rounded font-bold font-mono transition-all cursor-pointer flex items-center gap-1.5 ${
                    isAutoPilot ? 'bg-purple-600 border border-purple-400 text-white shadow-[0_0_12px_rgba(168,85,247,0.5)] scale-[1.02]' : 'bg-slate-950 hover:bg-slate-900 border border-purple-500/20 hover:border-purple-500/50 text-purple-400 hover:text-purple-300'
                  }`}
                  title="Auto-pass through remaining players (the 9 AI teams still bid for real)"
                >
                  {isAutoPilot ? <><span className="w-1.5 h-1.5 rounded-full bg-white animate-ping shrink-0" /><span>🤖 AUTOPILOT ON</span></> : <span>🤖 AUTOPILOT OFF</span>}
                </button>
                </div>
              </div>

              <AuctionRoom
                teams={teams}
                userTeamId={userTeamId}
                currentBidderId={currentBidderId}
                currentPlayer={currentPlayer}
                currentBid={currentBid}
                lotNumber={lotNumber}
                activeSet={phase === 'BOOST_ROUND' ? 'BOOST' : activeSet}
                auctioneerCall={auctioneerCall}
                hammer={hammer}
                onTeamClick={(team) => setInspectedTeam(team)}
              />

              {currentPlayer && (
                <div className="bg-slate-950 border border-cyan-500/10 rounded-xl p-3 shrink-0 space-y-2">
                  {/* Hammer count + the two opt-out controls share ONE row.
                      Vertical space here is taken straight out of the room
                      above, which is where the player's price and stats
                      live -- so this bar stays as short as it can be. */}
                  <div className="flex items-center gap-2">
                    <div className="flex items-center gap-1.5 shrink-0">
                      {[1, 2, 3].map(n => (
                        <span
                          key={n}
                          className={`h-1.5 w-5 rounded-full transition-all duration-300 ${
                            callStage >= n ? 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.6)]' : 'bg-slate-800'
                          }`}
                        />
                      ))}
                    </div>
                    <span className="text-[9px] font-bold uppercase tracking-widest text-amber-400/90 w-[86px] shrink-0">
                      {callStage === 0 ? '' : callStage === 1 ? 'Going once' : callStage === 2 ? 'Going twice' : 'Going thrice'}
                    </span>
                    <button
                      onClick={handleSitOut}
                      disabled={sittingOut || isPlaying}
                      className={`flex-1 px-2 py-1.5 rounded-md font-bold text-[9px] uppercase tracking-wider transition-all cursor-pointer border ${
                        sittingOut || isPlaying
                          ? 'bg-slate-900 border-slate-800 text-slate-700 cursor-not-allowed'
                          : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700'
                      }`}
                    >
                      {sittingOut ? 'Sitting out' : 'Skip player'}
                    </button>
                    <button
                      onClick={handleAutoBid}
                      disabled={isPlaying}
                      className={`flex-1 px-2 py-1.5 rounded-md font-bold text-[9px] uppercase tracking-wider transition-all cursor-pointer border ${
                        autoBidLimit !== null
                          ? 'bg-amber-500/15 border-amber-500/40 text-amber-300'
                          : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200 hover:border-slate-700'
                      }`}
                    >
                      {autoBidLimit !== null ? `Auto ${autoBidLimit.toFixed(1)} Cr` : 'Auto-bid'}
                    </button>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                  <button
                    onClick={handlePass}
                    disabled={paddleLocked}
                    className={`px-3 py-3.5 rounded-lg font-bold text-xs uppercase tracking-wider transition-all cursor-pointer ${
                      paddleLocked ? 'bg-slate-900 border border-slate-800 text-slate-600 cursor-not-allowed' : 'bg-slate-900 hover:bg-slate-800 border border-slate-800 text-slate-400 hover:text-slate-300'
                    }`}
                  >
                    PASS / DECLINE
                  </button>
                  <button
                    onClick={handleRaisePaddle}
                    disabled={paddleLocked}
                    className={`px-3 py-3.5 rounded-lg font-black text-xs tracking-widest uppercase transition-all cursor-pointer shadow-lg flex flex-col items-center justify-center leading-none ${
                      paddleLocked ? 'bg-slate-900 border border-slate-800 text-slate-600 cursor-not-allowed' : 'bg-cyan-500 text-slate-950 hover:bg-cyan-400 shadow-[0_0_15px_rgba(34,211,238,0.2)] hover:scale-[1.01]'
                    }`}
                  >
                    <span>{isPlaying ? 'AUCTION IN PROGRESS' : currentBid === 0 ? 'OPEN BIDDING' : 'RAISE PADDLE'}</span>
                    <span className="text-[8px] font-mono opacity-80 block mt-1 text-center font-bold">
                      {getNextBid(currentBid, currentPlayer.basePrice).toFixed(2)} CR
                    </span>
                  </button>
                  </div>
                </div>
              )}

              {/* Live ticker: the last few calls only. The full record lives
                  behind the history button -- a scrolling log beside the room
                  pushed the desks off screen and was unreadable at speed. */}
              <div className="shrink-0 h-[52px] overflow-hidden rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-1.5">
                <div className="flex flex-col-reverse gap-0.5">
                  {biddingLogs.slice(-3).map(log => (
                    <div key={log.id} className="text-[10px] font-mono truncate leading-tight">
                      {log.teamId === 'sold' ? <span className="text-emerald-400">{log.teamName}</span>
                        : log.teamId === 'unsold' ? <span className="text-slate-500">{log.teamName}</span>
                        : <span className="text-slate-400">{log.teamName} <span className="text-amber-300">{log.amount.toFixed(2)} Cr</span></span>}
                    </div>
                  ))}
                  {biddingLogs.length === 0 && (
                    <div className="text-[10px] font-mono text-slate-600">Auction feed…</div>
                  )}
                </div>
              </div>
            </div>

          </div>
        )}

        {/* ================= PHASE 4: NOMINATION ================= */}
        {phase === 'NOMINATION' && (
          <div className="flex-1 flex flex-col gap-6 animate-scale-up">
            <div className="text-center max-w-2xl mx-auto space-y-2 py-4">
              <span className="text-cyan-400 font-mono text-xs font-bold bg-cyan-950/40 border border-cyan-500/30 px-3 py-1 rounded uppercase tracking-widest">ACCELERATED PREPARATION ROUND</span>
              <h2 className="text-2xl md:text-3xl font-display font-extrabold text-white uppercase tracking-tight">Nominate Unsold Players for the Boost Round</h2>
              <p className="text-slate-400 text-xs leading-normal">
                All primary auction pools have been completed. Nominate up to <strong>5 players</strong> from the Unsold Pool below to bring them back to the block at a rapid-fire <strong>50% discount</strong>.
              </p>
            </div>

            {unsoldPool.length === 0 ? (
              <div className="bg-slate-950/50 border border-cyan-500/20 rounded-2xl p-12 text-center text-slate-400 flex flex-col items-center justify-center max-w-md mx-auto space-y-4 shadow-[0_0_30px_rgba(6,182,212,0.05)]">
                <CheckCircle className="w-12 h-12 text-cyan-400" />
                <div>
                  <h3 className="font-extrabold text-white text-base uppercase tracking-tight">Perfect Main Round!</h3>
                  <p className="text-xs text-slate-500 mt-1">Every single player on the auction block was bought!</p>
                </div>
                <button onClick={handleLaunchBoostRound} className="px-6 py-3.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-xs font-black tracking-widest uppercase shadow-[0_0_15px_rgba(34,211,238,0.2)] cursor-pointer">
                  CONCLUDE AUCTION SIMULATOR
                </button>
              </div>
            ) : (
              <div className="flex-1 flex flex-col gap-4 min-h-0">
                <div className="bg-slate-950/60 border border-cyan-500/20 shadow-[0_0_30px_rgba(6,182,212,0.05)] rounded-xl overflow-hidden flex-1 flex flex-col min-h-[400px]">
                  <div className="p-4 bg-slate-900 border-b border-cyan-500/10 flex flex-wrap items-center justify-between gap-3 text-xs font-mono font-bold">
                    <span className="text-slate-400">TOTAL UNSOLD POOL: <strong className="text-cyan-400">{unsoldPool.length}</strong> PLAYERS</span>
                    <span className="text-cyan-400 uppercase tracking-wider">YOUR NOMINATIONS: <strong className="text-slate-100">{nominatedIds.length} / 5</strong></span>
                  </div>
                  <div className="p-4 overflow-y-auto grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3.5 flex-1 custom-scrollbar">
                    {unsoldPool.map((p) => {
                      const isNominated = nominatedIds.includes(p.id);
                      return (
                        <button
                          key={p.id}
                          onClick={() => handleToggleNomination(p.id)}
                          className={`p-3.5 rounded-xl border text-left flex items-center justify-between gap-3 transition-all cursor-pointer relative group ${
                            isNominated ? 'border-cyan-400 bg-cyan-950/20 ring-1 ring-cyan-500/20' : 'border-slate-800 hover:border-cyan-500/20 bg-slate-950/40'
                          }`}
                        >
                          <div className="min-w-0">
                            <p className="font-bold text-xs uppercase tracking-tight text-slate-200 group-hover:text-cyan-400 truncate transition-colors">{p.name}</p>
                            <span className="text-[10px] text-slate-500 font-mono mt-1 block">★ {p.rating} • {p.role}</span>
                          </div>
                          <div className="text-right shrink-0">
                            <span className="text-[9px] text-slate-500 font-mono block font-bold">BASE PRICE</span>
                            <span className="text-cyan-400 font-bold font-mono text-xs block">{p.basePrice.toFixed(2)} CR</span>
                          </div>
                          <div className="absolute top-2 right-2 text-cyan-400 opacity-0 group-hover:opacity-100 transition-opacity">
                            <PlusCircle className="w-4 h-4 fill-current text-cyan-500" />
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div className="flex justify-center pt-3">
                  <button onClick={handleLaunchBoostRound} className="flex items-center gap-2.5 px-8 py-4 rounded-xl text-xs font-black uppercase tracking-widest bg-cyan-500 hover:bg-cyan-400 text-slate-950 transition-all scale-100 hover:scale-[1.01] shadow-[0_0_20px_rgba(34,211,238,0.3)] cursor-pointer">
                    <Flame className="w-3.5 h-3.5 fill-current" />
                    LAUNCH RAPID-FIRE BOOST AUCTION
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ================= PHASE 5: COMPLETED ================= */}
        {phase === 'COMPLETED' && finalStats && (
          <div className="flex-1 flex flex-col gap-6 animate-scale-up">
            <div className="text-center max-w-2xl mx-auto space-y-3 py-6">
              <span className="text-amber-400 font-mono text-xs font-bold bg-amber-400/10 border border-amber-400/20 px-3 py-1 rounded-full uppercase tracking-wider">TOURNAMENT AUCTION CONCLUDED</span>
              <h2 className="text-3xl md:text-4xl font-display font-black text-white tracking-tight flex items-center justify-center gap-2.5 uppercase">
                <Trophy className="w-8 h-8 text-cyan-400 shrink-0" />
                Roster Complete!
              </h2>
              <p className="text-slate-400 text-xs md:text-sm leading-normal">
                All 10 franchises have satisfied the squad regulations by drafting exactly <strong>20 players</strong>.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="bg-slate-950/80 border border-cyan-500/20 shadow-[0_0_30px_rgba(6,182,212,0.05)] rounded-2xl p-5 flex flex-col justify-between relative overflow-hidden group">
                <div>
                  <span className="text-[9px] text-cyan-400 font-mono font-bold tracking-widest uppercase block mb-1">👑 CHAMPION SQUAD BUILDER</span>
                  <div className="flex items-center gap-3.5 mt-2">
                    <div className={`w-12 h-12 rounded flex items-center justify-center text-slate-950 font-black text-lg skew-x-[-6deg] shadow-lg ${finalStats.champion.team.logo}`}>{finalStats.champion.team.shortName}</div>
                    <div>
                      <h4 className="font-extrabold text-white text-base truncate max-w-[170px] uppercase tracking-tight">{finalStats.champion.team.name}</h4>
                      <p className="text-xs text-slate-400 font-mono mt-0.5">Rating Score: <strong className="text-cyan-400 font-bold">{finalStats.champion.totalRating}</strong></p>
                    </div>
                  </div>
                </div>
                <div className="border-t border-cyan-500/10 pt-4 mt-4 text-xs text-slate-400 font-mono flex items-center justify-between">
                  <span>Spent: <strong className="text-slate-200">{finalStats.champion.spent.toFixed(2)} CR</strong></span>
                  <span>Avg Skill: <strong className="text-cyan-300 font-bold">★ {finalStats.champion.avgRating}</strong></span>
                </div>
              </div>

              <div className="bg-slate-950/80 border border-cyan-500/20 shadow-[0_0_30px_rgba(6,182,212,0.05)] rounded-2xl p-5 flex flex-col justify-between relative overflow-hidden">
                <div>
                  <span className="text-[9px] text-rose-400 font-mono font-bold tracking-widest uppercase block mb-1">💰 COSTLIEST ACQUISITION</span>
                  {finalStats.costliestBuy ? (
                    <div className="mt-2 space-y-1">
                      <p className="font-extrabold text-white text-base truncate uppercase tracking-tight">{finalStats.costliestBuy.player.name}</p>
                      <p className="text-xs text-slate-400 font-mono">Bought by <strong className="text-slate-200">{finalStats.costliestBuy.teamName}</strong></p>
                    </div>
                  ) : <p className="text-slate-500 text-xs italic mt-2">No buys recorded</p>}
                </div>
                {finalStats.costliestBuy && (
                  <div className="border-t border-cyan-500/10 pt-4 mt-4 text-xs font-mono flex items-center justify-between">
                    <span className="text-slate-400">Rating: <strong className="text-cyan-400 font-bold">★ {finalStats.costliestBuy.player.rating}</strong></span>
                    <span className="text-rose-500 font-extrabold">{finalStats.costliestBuy.price.toFixed(2)} CR</span>
                  </div>
                )}
              </div>

              <div className="bg-slate-950/80 border border-cyan-500/20 shadow-[0_0_30px_rgba(6,182,212,0.05)] rounded-2xl p-5 flex flex-col justify-between relative overflow-hidden">
                <div>
                  <span className="text-[9px] text-cyan-400 font-mono font-bold tracking-widest uppercase block mb-1">💎 BEST VALUE STEAL</span>
                  {finalStats.valueSteal ? (
                    <div className="mt-2 space-y-1">
                      <p className="font-extrabold text-white text-base truncate uppercase tracking-tight">{finalStats.valueSteal.player.name}</p>
                      <p className="text-xs text-slate-400 font-mono">Snared by <strong className="text-slate-200">{finalStats.valueSteal.teamName}</strong></p>
                    </div>
                  ) : <p className="text-slate-500 text-xs italic mt-2">No steals recorded</p>}
                </div>
                {finalStats.valueSteal && (
                  <div className="border-t border-cyan-500/10 pt-4 mt-4 text-xs font-mono flex items-center justify-between">
                    <span className="text-slate-400">Rating: <strong className="text-cyan-300 font-bold">★ {finalStats.valueSteal.player.rating}</strong></span>
                    <span className="text-cyan-400 font-bold">Bought: {finalStats.valueSteal.price.toFixed(2)} CR</span>
                  </div>
                )}
              </div>
            </div>

            <div className="bg-slate-950/80 border border-cyan-500/20 shadow-[0_0_35px_rgba(6,182,212,0.05)] rounded-2xl p-5 flex-1 flex flex-col min-h-0">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-cyan-500/10">
                <h3 className="font-display font-extrabold text-xs uppercase tracking-widest text-cyan-400 flex items-center gap-2">
                  <span className="w-1.5 h-3 bg-cyan-500 rounded-sm"></span>
                  Final Franchise Power Standings
                </h3>
                <div className="relative w-full max-w-xs">
                  <Search className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
                  <input
                    type="text"
                    placeholder="Search drafted rosters..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full bg-slate-900 border border-cyan-500/10 rounded-lg pl-9 pr-4 py-2 text-xs focus:outline-none focus:border-cyan-400 transition-colors placeholder:text-slate-500 text-slate-100 font-mono"
                  />
                </div>
              </div>
              <div className="divide-y divide-cyan-500/5 overflow-y-auto flex-1 custom-scrollbar max-h-[360px] pt-2">
                {filteredStandings.map((row, idx) => {
                  const isUser = row.team.id === userTeamId;
                  return (
                    <div key={row.team.id} className="py-3.5 flex flex-col md:flex-row md:items-center justify-between gap-4 px-2 hover:bg-slate-900/40 transition-colors rounded-lg">
                      <div className="flex items-center gap-3">
                        <span className="text-xs font-mono font-bold text-slate-500 w-4">{idx + 1}</span>
                        <button onClick={() => setInspectedTeam(row.team)} className={`w-9 h-9 rounded flex items-center justify-center text-slate-950 font-black text-xs skew-x-[-6deg] shadow border border-white/5 cursor-pointer ${row.team.logo}`}>{row.team.shortName}</button>
                        <div>
                          <div className="flex items-center gap-1.5">
                            <button onClick={() => setInspectedTeam(row.team)} className="font-bold text-sm text-slate-100 hover:text-cyan-400 transition-colors text-left uppercase tracking-tight">{row.team.name}</button>
                            {isUser && <span className="bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 text-[8px] px-1.5 py-0.5 rounded font-mono font-bold">YOU</span>}
                          </div>
                          <span className="text-[10px] text-slate-500 font-mono block mt-0.5 uppercase">Manager Strategy: {row.team.strategy.name}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-6 text-xs font-mono text-slate-400">
                        <div className="text-right"><span className="text-[9px] text-slate-500 block uppercase font-bold">ROSTER SCORE</span><span className="text-rose-500 font-black text-xs">{row.totalRating} pts</span></div>
                        <div className="text-right"><span className="text-[9px] text-slate-500 block uppercase font-bold">AVG ATTRIBUTE</span><span className="text-cyan-300 font-bold text-xs">★ {row.avgRating}</span></div>
                        <div className="text-right"><span className="text-[9px] text-slate-500 block uppercase font-bold">REMAINING CASH</span><span className="text-cyan-400 font-bold text-xs">{row.team.budget.toFixed(2)} CR</span></div>
                        <button onClick={() => setInspectedTeam(row.team)} className="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 border border-cyan-500/20 rounded text-[10px] font-bold text-cyan-400 hover:text-cyan-300 transition-all cursor-pointer uppercase tracking-wider">View Squad</button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="flex justify-center pt-2">
              <button onClick={handleResetGame} className="flex items-center gap-2 px-8 py-3.5 bg-cyan-500 hover:bg-cyan-400 text-slate-950 rounded-lg text-xs font-black uppercase tracking-widest transition-all shadow-[0_0_15px_rgba(34,211,238,0.2)] cursor-pointer">
                <RotateCcw className="w-3.5 h-3.5" />
                PLAY AGAIN
              </button>
            </div>
          </div>
        )}
      </main>

      <SquadModal team={inspectedTeam} onClose={() => setInspectedTeam(null)} />

      {/* Full bidding record, on demand -- deliberately NOT beside the room. */}
      {showHistory && (
        <div className="fixed inset-0 z-[60] bg-slate-950/85 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => setShowHistory(false)}>
          <div className="w-full max-w-2xl max-h-[80vh] flex flex-col rounded-2xl border border-slate-700 bg-slate-950 overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="px-4 py-3 border-b border-slate-800 flex items-center justify-between shrink-0">
              <span className="font-display font-extrabold text-white uppercase tracking-tight">Bidding History</span>
              <button onClick={() => setShowHistory(false)} className="p-1 rounded hover:bg-slate-800 text-slate-400 cursor-pointer">
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto p-2">
              <BiddingLog logs={biddingLogs} teams={teams} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
