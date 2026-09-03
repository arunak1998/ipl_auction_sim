import { BiddingLog as LogType, Team } from '../types';
import { Terminal, Send, ShieldCheck, HelpCircle } from 'lucide-react';
import { useEffect, useRef } from 'react';

interface BiddingLogProps {
  logs: LogType[];
  teams: Team[];
}

export default function BiddingLog({ logs, teams }: BiddingLogProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto scroll to bottom when new logs appear
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div className="bg-slate-950/80 border border-cyan-500/20 rounded-xl overflow-hidden shadow-[0_0_30px_rgba(6,182,212,0.05)] h-full flex flex-col" id="bidding-log-container">
      <div className="bg-slate-900 px-4 py-3.5 border-b border-cyan-500/30 flex items-center gap-2">
        <Terminal className="w-4 h-4 text-cyan-400 animate-pulse" />
        <h2 className="font-display font-extrabold text-cyan-400 tracking-wider text-xs uppercase">BIDDING HISTORY</h2>
      </div>

      <div 
        ref={containerRef}
        className="flex-1 overflow-y-auto p-4 space-y-4 font-sans text-xs scroll-smooth custom-scrollbar bg-slate-950/50 relative"
        id="ticker-scroller"
      >
        {logs.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-slate-500 text-center px-4 py-8">
            <HelpCircle className="w-8 h-8 text-slate-700 mb-2 animate-bounce" />
            <p className="text-xs uppercase tracking-widest font-bold text-slate-600">No Bids Yet</p>
            <p className="text-[10px] text-slate-500/70 mt-1">Open the bidding block to initiate counter offers.</p>
          </div>
        ) : (
          <div className="relative pl-4 space-y-4">
            {/* Timeline line */}
            <div className="absolute left-[7px] top-1 bottom-1 w-0.5 bg-slate-800" />

            {logs.map((log, index) => {
              const team = teams.find(t => t.id === log.teamId);
              const isSystem = log.teamId === 'system';
              const isSold = log.teamId === 'sold';
              const isUnsold = log.teamId === 'unsold';
              const isLatest = index === logs.length - 1;

              // Bullet colors and classes
              let bulletClass = "bg-slate-700";
              if (isLatest) {
                bulletClass = "bg-rose-500 shadow-[0_0_10px_rgba(244,63,94,0.8)] scale-110";
              } else if (isSold) {
                bulletClass = "bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.5)]";
              } else if (isUnsold) {
                bulletClass = "bg-red-500";
              } else if (team?.isHuman) {
                bulletClass = "bg-cyan-500 shadow-[0_0_8px_rgba(6,182,212,0.5)]";
              }

              if (isSystem) {
                return (
                  <div key={log.id} className="relative flex gap-3 animate-fade-in pl-2">
                    <div className="absolute left-[-16px] top-1.5 w-2 h-2 rounded-full bg-slate-700" />
                    <div className="text-[11px] font-mono text-slate-400 italic bg-slate-900/40 px-2 py-1 border border-slate-800/60 rounded">
                      {log.amount > 0 ? `Base Price: ${log.amount.toFixed(2)} Cr` : log.teamName}
                    </div>
                  </div>
                );
              }

              if (isSold) {
                return (
                  <div key={log.id} className="relative flex gap-3 animate-fade-in pl-2">
                    <div className="absolute left-[-17px] top-1.5 w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
                    <div className="text-[11px] bg-emerald-950/20 border border-emerald-900/50 text-emerald-400 p-2 rounded-lg w-full flex items-center justify-between font-bold">
                      <span>{log.teamName}</span>
                      <span className="font-mono text-xs">{log.amount.toFixed(2)} Cr</span>
                    </div>
                  </div>
                );
              }

              if (isUnsold) {
                return (
                  <div key={log.id} className="relative flex gap-3 animate-fade-in pl-2">
                    <div className="absolute left-[-17px] top-1.5 w-2.5 h-2.5 rounded-full bg-red-500" />
                    <div className="text-[11px] bg-red-950/10 border border-red-900/40 text-red-400 p-2 rounded-lg w-full text-center italic font-semibold">
                      {log.teamName}
                    </div>
                  </div>
                );
              }

              // Normal Bid Log
              const opponentLog = index > 0 ? logs[index - 1] : null;
              const hasOpponent = opponentLog && opponentLog.teamId !== 'system' && opponentLog.teamId !== 'sold' && opponentLog.teamId !== 'unsold';
              const counterDetail = hasOpponent 
                ? `Countering ${opponentLog.teamName} bid of ${opponentLog.amount.toFixed(2)} Cr` 
                : "Initial Set Bid";

              return (
                <div 
                  key={log.id} 
                  className={`relative flex gap-3 animate-fade-in pl-2 transition-all ${isLatest ? 'opacity-100' : 'opacity-70'}`}
                >
                  <div className={`absolute left-[-17px] top-1.5 w-2.5 h-2.5 rounded-full ${bulletClass}`} />
                  <div className="text-[11px] flex-1">
                    <div className={`font-bold ${isLatest ? 'text-rose-400' : team?.isHuman ? 'text-cyan-400' : 'text-slate-300'}`}>
                      {log.teamName} bids {log.amount.toFixed(2)} Cr
                    </div>
                    <div className="text-[10px] text-slate-500 font-mono mt-0.5">
                      {counterDetail}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
