import { useState } from 'react';
import { Team, Player } from '../types';
import { X, User, Shield, Info, Users, Star, Target, Coins, Flag, Percent, TrendingUp } from 'lucide-react';

interface SquadModalProps {
  team: Team | null;
  onClose: () => void;
}

export default function SquadModal({ team, onClose }: SquadModalProps) {
  const [activeTab, setActiveTab] = useState<'roster' | 'strategy'>('roster');

  if (!team) return null;

  const totalSpent = 125.0 - team.budget;
  const avgRating = team.squad.length > 0 
    ? (team.squad.reduce((acc, current) => acc + current.player.rating, 0) / team.squad.length).toFixed(1)
    : '0.0';

  // Group squad by primary roles
  const groupedSquad = {
    'Batsman': team.squad.filter(p => p.player.role === 'Batsman'),
    'Wicketkeeper': team.squad.filter(p => p.player.role === 'Wicketkeeper'),
    'All-Rounder': team.squad.filter(p => p.player.role === 'All-Rounder'),
    // Split, now that bowler_subtype is real data rather than a guess --
    // "4 bowlers" hides whether a squad has any spin at all.
    'Fast Bowler': team.squad.filter(p => p.player.role === 'Fast Bowler'),
    'Spin Bowler': team.squad.filter(p => p.player.role === 'Spin Bowler'),
    'Uncapped': team.squad.filter(p => p.player.role === 'Uncapped'),
  };

  const roleCounts = {
    batsman: team.squad.filter(p => p.player.role === 'Batsman').length,
    wicketkeeper: team.squad.filter(p => p.player.role === 'Wicketkeeper').length,
    allrounder: team.squad.filter(p => p.player.role === 'All-Rounder').length,
    bowler: team.squad.filter(p => p.player.role === 'Fast Bowler' || p.player.role === 'Spin Bowler').length,
    uncapped: team.squad.filter(p => p.player.role === 'Uncapped').length
  };

  // Foreign/Overseas player count calculation
  const foreignCount = team.squad.filter(p => p.player.country && p.player.country.trim().toLowerCase() !== 'india').length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/85 backdrop-blur-md animate-fade-in" id="squad-modal-overlay">
      <div className="bg-slate-900 border-2 border-cyan-500/30 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col overflow-hidden shadow-[0_0_50px_rgba(34,211,238,0.15)] animate-scale-up" id="squad-modal-content">
        
        {/* Header section with Team Logo/Branding */}
        <div className={`p-6 text-white ${team.logo} relative flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-cyan-500/20`}>
          <button 
            onClick={onClose}
            className="absolute top-4 right-4 bg-slate-950/60 hover:bg-slate-950 border border-white/10 hover:border-white/30 text-white p-2 rounded-full transition-all cursor-pointer"
            id="close-squad-modal-btn"
          >
            <X className="w-4 h-4" />
          </button>

          <div className="flex items-center gap-4">
            <div className="w-14 h-14 bg-white/10 rounded flex items-center justify-center text-white font-black text-2xl border border-white/20 skew-x-[-6deg] shadow-lg">
              {team.shortName}
            </div>
            <div>
              <h2 className="text-xl md:text-2xl font-display font-black tracking-tight uppercase">{team.name}</h2>
              <p className="text-white/80 text-xs mt-1 md:max-w-md uppercase font-mono tracking-tight text-[10px]">{team.strategy.description}</p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2 text-xs font-mono">
            <div className="bg-slate-950/65 border border-white/10 rounded px-3 py-2 flex flex-col">
              <span className="text-[9px] text-white/60 font-bold uppercase">PURSE REMAINING</span>
              <span className="text-cyan-400 font-extrabold text-sm font-mono mt-0.5">{team.budget.toFixed(2)} CR</span>
            </div>
            <div className="bg-slate-950/65 border border-white/10 rounded px-3 py-2 flex flex-col">
              <span className="text-[9px] text-white/60 font-bold uppercase">BUDGET SPENT</span>
              <span className="text-rose-400 font-extrabold text-sm font-mono mt-0.5">{totalSpent.toFixed(2)} CR</span>
            </div>
            <div className="bg-slate-950/65 border border-white/10 rounded px-3 py-2 flex flex-col">
              <span className="text-[9px] text-white/60 font-bold uppercase">AVG RATING</span>
              <span className="text-cyan-400 font-extrabold text-sm font-mono mt-0.5 flex items-center gap-1">
                <Star className="w-3.5 h-3.5 fill-cyan-400 text-cyan-400" />
                {avgRating}
              </span>
            </div>
          </div>
        </div>

        {/* Tab Navigation Menu */}
        <div className="bg-slate-950/60 border-b border-cyan-500/15 px-6 flex gap-4 text-xs font-mono">
          <button
            onClick={() => setActiveTab('roster')}
            className={`py-3.5 border-b-2 font-black uppercase tracking-wider flex items-center gap-2 transition-all cursor-pointer ${
              activeTab === 'roster' 
                ? 'border-cyan-400 text-cyan-400' 
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
            id="squad-tab-roster"
          >
            <Users className="w-4 h-4" />
            Acquired Roster ({team.squad.length})
          </button>
          <button
            onClick={() => setActiveTab('strategy')}
            className={`py-3.5 border-b-2 font-black uppercase tracking-wider flex items-center gap-2 transition-all cursor-pointer ${
              activeTab === 'strategy' 
                ? 'border-cyan-400 text-cyan-400' 
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
            id="squad-tab-strategy"
          >
            <Target className="w-4 h-4" />
            Strategist Rules & Guidelines
          </button>
        </div>

        {/* Dynamic Tab Body */}
        <div className="flex-1 overflow-y-auto p-6 bg-slate-950/20 custom-scrollbar">
          
          {activeTab === 'roster' ? (
            /* Tab 1: Standard Roster list */
            <div className="space-y-6">
              {team.squad.length === 0 ? (
                <div className="text-center py-16 text-slate-500">
                  <User className="w-12 h-12 text-slate-600 mx-auto mb-3 animate-pulse" />
                  <p className="text-sm uppercase font-mono text-xs">No players acquired yet. Participate in the auction to fill the squad!</p>
                </div>
              ) : (
                Object.entries(groupedSquad).map(([roleGroup, bids]) => {
                  if (bids.length === 0) return null;
                  return (
                    <div key={roleGroup} className="space-y-2.5">
                      <h3 className="text-xs font-extrabold text-cyan-400 uppercase tracking-widest flex items-center gap-2">
                        <span className="w-1.5 h-3 bg-cyan-500 rounded-sm"></span>
                        {roleGroup}s ({bids.length})
                      </h3>
                      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                        {bids.map((bid) => {
                          const isForeignPlayer = bid.player.country && bid.player.country.trim().toLowerCase() !== 'india';
                          return (
                            <div 
                              key={bid.player.id}
                              className="bg-slate-900 border border-cyan-500/5 hover:border-cyan-500/20 rounded p-3.5 flex items-center justify-between gap-3 transition-all group"
                            >
                              <div className="min-w-0">
                                <div className="flex items-center gap-1.5">
                                  <p className="font-bold text-xs uppercase tracking-tight text-slate-200 group-hover:text-cyan-400 truncate">
                                    {bid.player.name}
                                  </p>
                                  {isForeignPlayer && (
                                    <span className="bg-amber-500/10 border border-amber-500/20 text-amber-400 text-[8px] px-1 rounded uppercase font-bold shrink-0 font-mono">
                                      OS
                                    </span>
                                  )}
                                </div>
                                <div className="flex items-center gap-1.5 mt-1 text-[10px] text-slate-500 font-mono uppercase">
                                  <span className="bg-slate-950 border border-cyan-500/10 px-1.5 py-0.5 rounded text-cyan-400 font-bold">
                                    ★ {bid.player.rating}
                                  </span>
                                  <span>{bid.player.country}</span>
                                </div>
                              </div>

                              <div className="text-right shrink-0">
                                <span className="text-[9px] text-slate-500 block font-mono font-bold">BOUGHT FOR</span>
                                <span className="text-rose-500 font-extrabold font-mono text-xs block">
                                  {bid.buyPrice.toFixed(2)} CR
                                </span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          ) : (
            /* Tab 2: Strategist Rules Dashboard */
            <div className="space-y-6">
              
              {/* Vision Card */}
              <div className="bg-slate-900/60 border border-cyan-500/15 rounded-xl p-5">
                <h3 className="text-xs font-mono font-bold text-cyan-400 uppercase tracking-widest mb-2 flex items-center gap-2">
                  <Shield className="w-4 h-4 text-cyan-400" />
                  FRANCHISE PHILOSOPHY & BIDDING STRATEGY
                </h3>
                <p className="text-lg font-bold text-white uppercase">{team.strategy.name} Style</p>
                <p className="text-xs text-slate-400 leading-relaxed mt-2 uppercase font-mono tracking-tight text-[11px]">
                  {team.strategy.description}
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mt-4 text-xs font-mono">
                  <div className="bg-slate-950/50 p-2.5 rounded border border-cyan-500/5">
                    <span className="text-[9px] text-slate-500 block font-bold uppercase">MAX BID THRESHOLD</span>
                    <span className="text-rose-400 font-extrabold text-sm">{team.strategy.absoluteMaxBid.toFixed(2)} CR</span>
                  </div>
                  <div className="bg-slate-950/50 p-2.5 rounded border border-cyan-500/5">
                    <span className="text-[9px] text-slate-500 block font-bold uppercase">MARQUEE PREFERENCE</span>
                    <span className="text-cyan-400 font-extrabold text-sm">{team.strategy.marqueeWeight.toFixed(1)}x Priority</span>
                  </div>
                  {team.strategy.conservativeThreshold && (
                    <div className="bg-slate-950/50 p-2.5 rounded border border-cyan-500/5">
                      <span className="text-[9px] text-slate-500 block font-bold uppercase">BARGAIN TRIGGER</span>
                      <span className="text-amber-400 font-extrabold text-sm">{team.strategy.conservativeThreshold}x Base Max</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Strict Structural Limits */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                
                {/* Rule 1: Squad Size and Foreign limits */}
                <div className="bg-slate-900/60 border border-cyan-500/15 rounded-xl p-5 flex flex-col justify-between">
                  <div>
                    <h3 className="text-xs font-mono font-bold text-cyan-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                      <Flag className="w-4 h-4 text-amber-500" />
                      STRICT COMPLIANCE DIRECTIVES
                    </h3>
                    <div className="space-y-4">
                      {/* Foreign Limit */}
                      <div>
                        <div className="flex justify-between text-xs font-mono mb-1.5">
                          <span className="text-slate-300 font-bold uppercase">FOREIGN PLAYERS LIMIT (MAX 8)</span>
                          <span className={`font-black ${foreignCount > 8 ? 'text-rose-500' : foreignCount === 8 ? 'text-amber-400' : 'text-cyan-400'}`}>
                            {foreignCount} / 8 SIGNED
                          </span>
                        </div>
                        <div className="h-2 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
                          <div 
                            className={`h-full rounded-full transition-all duration-500 ${
                              foreignCount > 8 
                                ? 'bg-rose-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]' 
                                : foreignCount === 8 
                                  ? 'bg-amber-500' 
                                  : 'bg-gradient-to-r from-cyan-600 to-cyan-400'
                            }`}
                            style={{ width: `${Math.min(100, (foreignCount / 8) * 100)}%` }}
                          />
                        </div>
                        <p className="text-[10px] text-slate-500 mt-2 font-mono uppercase font-bold leading-normal">
                          * Strict regulation state that no team may roster more than 8 overseas players.
                        </p>
                      </div>

                      {/* Squad Size */}
                      <div>
                        <div className="flex justify-between text-xs font-mono mb-1.5">
                          <span className="text-slate-300 font-bold uppercase">TOTAL ROSTER SLOTS FILLED</span>
                          <span className="text-cyan-400 font-black">{team.squad.length} / 20</span>
                        </div>
                        <div className="h-2 bg-slate-950 rounded-full overflow-hidden border border-slate-800">
                          <div 
                            className="h-full bg-gradient-to-r from-emerald-600 to-emerald-400 rounded-full transition-all duration-500"
                            style={{ width: `${(team.squad.length / 20) * 100}%` }}
                          />
                        </div>
                        <p className="text-[10px] text-slate-500 mt-2 font-mono uppercase font-bold leading-normal">
                          * Exactly 20 players are required to complete the franchise roster successfully.
                        </p>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Role requirements Comparison */}
                <div className="bg-slate-900/60 border border-cyan-500/15 rounded-xl p-5">
                  <h3 className="text-xs font-mono font-bold text-cyan-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                    <Target className="w-4 h-4 text-emerald-400" />
                    ROLE-SPECIFIC SQUAD BREAKDOWNS
                  </h3>
                  <div className="space-y-2.5 font-mono text-xs">
                    {(Object.keys(team.strategy.targetRoleCounts) as Array<keyof typeof team.strategy.targetRoleCounts>).map((roleKey) => {
                      const target = team.strategy.targetRoleCounts[roleKey];
                      const current = roleCounts[roleKey];
                      const roleName = {
                        batsman: 'Batsmen',
                        wicketkeeper: 'Keepers',
                        allrounder: 'All-Rounders',
                        bowler: 'Specialist Bowlers',
                        uncapped: 'Uncapped Domestic'
                      }[roleKey];

                      const isMet = current >= target;

                      return (
                        <div key={roleKey} className="bg-slate-950/40 p-2 rounded border border-cyan-500/5 flex items-center justify-between">
                          <span className="text-slate-300 font-bold uppercase">{roleName}</span>
                          <div className="flex items-center gap-2">
                            <span className="text-slate-500 text-[10px]">TARGET: {target}</span>
                            <span className={`px-2 py-0.5 rounded text-[10px] font-black ${
                              isMet 
                                ? 'bg-emerald-950/50 text-emerald-400 border border-emerald-500/30' 
                                : 'bg-rose-950/50 text-rose-400 border border-rose-500/30'
                            }`}>
                              {current} / {target} {isMet ? '✔ MET' : 'PENDING'}
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

              </div>

              {/* Budget distribution constraints */}
              <div className="bg-slate-900/60 border border-cyan-500/15 rounded-xl p-5">
                <h3 className="text-xs font-mono font-bold text-cyan-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                  <Coins className="w-4 h-4 text-cyan-400" />
                  IDEAL PURSE DISTRIBUTION PLAN
                </h3>
                <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs font-mono">
                  {(Object.keys(team.strategy.idealBudgetDistribution) as Array<keyof typeof team.strategy.idealBudgetDistribution>).map((roleKey) => {
                    const allocated = team.strategy.idealBudgetDistribution[roleKey];
                    const roleName = {
                      batsman: 'Batsmen',
                      wicketkeeper: 'Keepers',
                      allrounder: 'All-Rounders',
                      bowler: 'Bowlers',
                      uncapped: 'Uncapped'
                    }[roleKey];

                    // Calculate actual spent on this role
                    let spent = 0;
                    if (roleKey === 'batsman') spent = team.squad.filter(p => p.player.role === 'Batsman').reduce((sum, b) => sum + b.buyPrice, 0);
                    else if (roleKey === 'wicketkeeper') spent = team.squad.filter(p => p.player.role === 'Wicketkeeper').reduce((sum, b) => sum + b.buyPrice, 0);
                    else if (roleKey === 'allrounder') spent = team.squad.filter(p => p.player.role === 'All-Rounder').reduce((sum, b) => sum + b.buyPrice, 0);
                    else if (roleKey === 'bowler') spent = team.squad.filter(p => p.player.role === 'Fast Bowler' || p.player.role === 'Spin Bowler').reduce((sum, b) => sum + b.buyPrice, 0);
                    else if (roleKey === 'uncapped') spent = team.squad.filter(p => p.player.role === 'Uncapped').reduce((sum, b) => sum + b.buyPrice, 0);

                    const isOver = spent > allocated;

                    return (
                      <div key={roleKey} className="bg-slate-950/60 p-3 rounded-lg border border-cyan-500/5 flex flex-col justify-between">
                        <span className="text-[10px] text-slate-400 block font-bold uppercase truncate">{roleName}</span>
                        <div className="mt-2.5">
                          <span className="text-[9px] text-slate-500 block uppercase">PLAN ALLOCATION</span>
                          <span className="text-cyan-400 font-extrabold text-xs block">{allocated.toFixed(2)} CR</span>
                        </div>
                        <div className="mt-1.5 pt-1.5 border-t border-slate-800/50">
                          <span className="text-[9px] text-slate-500 block uppercase">ACTUAL SPENT</span>
                          <span className={`font-extrabold text-xs block ${isOver ? 'text-rose-400' : 'text-emerald-400'}`}>
                            {spent.toFixed(2)} CR
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

            </div>
          )}

        </div>

        {/* Modal Footer warning */}
        <div className="p-4 bg-slate-950 border-t border-cyan-500/10 flex items-center gap-2 text-slate-500 text-[10px] font-mono uppercase font-bold">
          <Info className="w-4 h-4 text-cyan-400 shrink-0" />
          <span>Rules state each franchise must strictly enforce the <strong>8 foreign players maximum</strong> rule and construct exactly <strong>20 players</strong> overall.</span>
        </div>
      </div>
    </div>
  );
}
