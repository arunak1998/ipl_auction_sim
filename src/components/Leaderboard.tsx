import { Team } from '../types';
import { Award, User, Coins, Users } from 'lucide-react';

interface LeaderboardProps {
  teams: Team[];
  userTeamId: string;
  activeBidderId: string | null;
  onTeamClick: (team: Team) => void;
}

export default function Leaderboard({ teams, userTeamId, activeBidderId, onTeamClick }: LeaderboardProps) {
  // Sort teams by budget descending (or maybe squad size descending as secondary)
  const sortedTeams = [...teams].sort((a, b) => b.budget - a.budget || b.squad.length - a.squad.length);

  return (
    <div className="bg-slate-950/80 border border-cyan-500/20 rounded-xl overflow-hidden shadow-[0_0_30px_rgba(6,182,212,0.05)] h-full flex flex-col" id="leaderboard-container">
      <div className="bg-slate-900 px-4 py-3.5 border-b border-cyan-500/30 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Award className="w-4 h-4 text-cyan-400 animate-pulse" />
          <h2 className="font-display font-extrabold text-cyan-400 tracking-wider text-xs uppercase">PURSE LEADERBOARD</h2>
        </div>
        <span className="text-[9px] text-cyan-300 bg-cyan-950/40 border border-cyan-500/30 px-2 py-0.5 rounded font-mono font-bold uppercase tracking-wider">
          10 Teams
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-2 custom-scrollbar bg-slate-950/50" id="leaderboard-list">
        {sortedTeams.map((team, idx) => {
          const isUser = team.id === userTeamId;
          const isActiveBidder = team.id === activeBidderId;
          const isFull = team.squad.length >= 20;

          let borderClass = "border-l-2 border-slate-800 bg-slate-900/30 opacity-75 hover:opacity-100 hover:bg-slate-900/60";
          let textClass = "text-slate-100";
          let budgetClass = "text-slate-300";
          let tagText = team.strategy.name + " AI";

          if (isActiveBidder) {
            borderClass = "border-l-2 border-rose-500 bg-rose-950/20 shadow-[inset_4px_0_12px_rgba(244,63,94,0.1)]";
            textClass = "text-rose-200 font-bold";
            budgetClass = "text-rose-400 font-bold";
            tagText = isUser ? "MANUAL CONTROL" : team.strategy.name + " AI";
          } else if (isUser) {
            borderClass = "border-l-2 border-cyan-400 bg-cyan-950/20 shadow-[inset_4px_0_12px_rgba(34,211,238,0.1)]";
            textClass = "text-cyan-100 font-bold";
            budgetClass = "text-cyan-400 font-bold";
            tagText = "MANUAL CONTROL";
          }

          return (
            <button
              key={team.id}
              onClick={() => onTeamClick(team)}
              className={`w-full text-left p-2.5 transition-all rounded-r flex items-center justify-between gap-2 cursor-pointer border-y border-r border-transparent ${borderClass}`}
              id={`leaderboard-team-${team.id}`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <div className={`w-8 h-8 rounded shrink-0 flex items-center justify-center text-slate-950 font-black text-xs skew-x-[-6deg] ${team.logo}`}>
                  {team.shortName}
                </div>

                <div className="min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className={`text-xs uppercase tracking-tight truncate max-w-[120px] ${textClass}`}>
                      {team.name}
                    </span>
                  </div>
                  <span className="text-[9px] text-slate-500 font-mono uppercase tracking-wider block">
                    {tagText}
                  </span>
                </div>
              </div>

              {/* Purse & Squad count details */}
              <div className="text-right flex flex-col items-end justify-center font-mono">
                <div className="text-xs font-bold leading-none tracking-tight">
                  <span className={budgetClass}>{team.budget.toFixed(2)} CR</span>
                </div>
                <div className="text-[10px] text-slate-500 italic mt-1 font-medium">
                  {team.squad.length}/20
                </div>
              </div>
            </button>
          );
        })}
      </div>
      <div className="p-2.5 bg-slate-950 border-t border-cyan-500/20 text-[9px] text-slate-500 text-center font-mono uppercase tracking-wider">
        Click team to inspect roster
      </div>
    </div>
  );
}
