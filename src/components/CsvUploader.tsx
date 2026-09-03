import React, { useState, useRef } from 'react';
import { Player } from '../types';
import { Upload, AlertCircle, FileText, CheckCircle } from 'lucide-react';

interface CsvUploaderProps {
  onPlayersParsed: (players: Player[]) => void;
  playerCount: number;
}

export default function CsvUploader({ onPlayersParsed, playerCount }: CsvUploaderProps) {
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const parseCsvContent = (text: string) => {
    try {
      const lines = text.split(/\r?\n/);
      if (lines.length < 2) {
        throw new Error('CSV is empty or missing headers');
      }

      // Parse headers
      const firstLine = lines[0];
      const separator = firstLine.includes('\t') ? '\t' : ',';
      const headers = firstLine.split(separator).map(h => h.trim().toLowerCase().replace(/['"“”]/g, ''));
      
      const nameIdx = headers.findIndex(h => h === 'full name' || h.includes('name') || h.includes('player'));
      const setIdx = headers.findIndex(h => h === 'set' || h.includes('set') || h.includes('group') || h.includes('round'));
      const countryIdx = headers.findIndex(h => h === 'country' || h.includes('country') || h.includes('nation'));
      const ageIdx = headers.findIndex(h => h === 'age' || h.includes('age'));
      const roleIdx = headers.findIndex(h => h === 'role' || h.includes('role') || h.includes('primary') || h.includes('position'));
      const battingIdx = headers.findIndex(h => h.includes('batting') || h.includes('style') || h.includes('hand') || h.includes('batting ha'));
      const bowlingIdx = headers.findIndex(h => h.includes('bowling') || h.includes('bowling style') || h.includes('bowling'));
      const statusIdx = headers.findIndex(h => h === 'capped/uncapped' || h.includes('status') || h.includes('capped'));
      const priceIdx = headers.findIndex(h => h === 'base-price' || h.includes('price') || h.includes('crore') || h.includes('base'));

      if (nameIdx === -1 || priceIdx === -1 || roleIdx === -1) {
        throw new Error('Required columns not found. Ensure CSV has headers like "Full Name", "Base-Price", "Role"');
      }

      const parsedPlayers: Player[] = [];

      for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;

        // Custom split to handle commas inside quotes if any
        let cols: string[] = [];
        let insideQuotes = false;
        let currentWord = '';

        for (let charIdx = 0; charIdx < line.length; charIdx++) {
          const char = line[charIdx];
          if (char === '"' || char === "'") {
            insideQuotes = !insideQuotes;
          } else if (char === separator && !insideQuotes) {
            cols.push(currentWord.trim());
            currentWord = '';
          } else {
            currentWord += char;
          }
        }
        cols.push(currentWord.trim());

        if (cols.length <= Math.max(nameIdx, priceIdx, roleIdx)) continue;

        const name = cols[nameIdx]?.replace(/['"“”]/g, '') || '';
        const rawPrice = cols[priceIdx]?.replace(/['"“”]/g, '') || '';
        let basePrice = parseFloat(rawPrice.replace(/[^\d.]/g, '')); // Strip units if present
        
        // Handle edge cases where price is represented in Lakhs instead of Crores
        if (basePrice > 20) {
          // If price is e.g. 20, 50, 200 (Lakhs), convert to Crores (e.g. 200 Lakhs = 2.00 Crores)
          basePrice = basePrice / 100;
        }

        if (!name || isNaN(basePrice)) continue;

        const setVal = setIdx !== -1 ? cols[setIdx]?.replace(/['"“”]/g, '').trim() : undefined;
        const countryVal = countryIdx !== -1 ? cols[countryIdx]?.replace(/['"“”]/g, '').trim() : 'India';
        const ageVal = ageIdx !== -1 ? parseInt(cols[ageIdx]?.replace(/[^\d]/g, '') || '') : undefined;
        const battingVal = battingIdx !== -1 ? cols[battingIdx]?.replace(/['"“”]/g, '').trim() : undefined;
        const bowlingVal = bowlingIdx !== -1 ? cols[bowlingIdx]?.replace(/['"“”]/g, '').trim() : undefined;

        // Normalise role
        const rawRole = cols[roleIdx]?.toLowerCase() || '';
        let role: Player['role'] = 'Batsman';
        if (rawRole.includes('keeper') || rawRole.includes('wk') || rawRole.includes('wicket') || rawRole.includes('wkt')) {
          role = 'Wicketkeeper';
        } else if (rawRole.includes('all') || rawRole.includes('ar') || rawRole.includes('rounder')) {
          role = 'All-Rounder';
        } else if (rawRole.includes('fast') || rawRole.includes('pace') || rawRole.includes('seam') || rawRole.includes('medium')) {
          role = 'Fast Bowler';
        } else if (rawRole.includes('spin') || rawRole.includes('spinner') || rawRole.includes('leg') || rawRole.includes('off')) {
          role = 'Spin Bowler';
        } else if (rawRole.includes('bowl') || rawRole.includes('bowler')) {
          if (bowlingVal?.toLowerCase().includes('spin') || bowlingVal?.toLowerCase().includes('ob') || bowlingVal?.toLowerCase().includes('lb')) {
            role = 'Spin Bowler';
          } else {
            role = 'Fast Bowler';
          }
        } else if (rawRole.includes('uncapped') || rawRole.includes('youth')) {
          role = 'Uncapped';
        } else if (rawRole.includes('bat') || rawRole.includes('batter') || rawRole.includes('batsman')) {
          role = 'Batsman';
        }

        // Capped / Uncapped status
        let status: Player['status'] = 'Capped';
        if (statusIdx !== -1 && cols[statusIdx]) {
          const rawStatus = cols[statusIdx].toLowerCase();
          if (rawStatus.includes('uncapped') || rawStatus.includes('no') || rawStatus.includes('false')) {
            status = 'Uncapped';
            if (!setVal) {
              role = 'Uncapped';
            }
          }
        } else if (basePrice < 0.50) {
          status = 'Uncapped';
          if (!setVal) {
            role = 'Uncapped';
          }
        }

        // Ratings generator: map base price (0.20 to 2.0 Crores) to realistic rating (75 to 98)
        let rating = 75 + Math.floor(Math.random() * 10);
        if (basePrice >= 2.0) {
          rating = 90 + Math.floor(Math.random() * 9); // 90 to 98
        } else if (basePrice >= 1.0) {
          rating = 83 + Math.floor(Math.random() * 8); // 83 to 90
        } else if (basePrice >= 0.50) {
          rating = 79 + Math.floor(Math.random() * 6); // 79 to 84
        }

        // Make top players Marquee if price is high
        const isMarquee = basePrice >= 2.0 && rating >= 92;

        parsedPlayers.push({
          id: `csv-${i}-${Date.now()}`,
          name,
          basePrice,
          role,
          status,
          rating,
          isMarquee,
          country: countryVal || 'India',
          set: setVal,
          age: ageVal,
          battingStyle: battingVal,
          bowlingStyle: bowlingVal,
        });
      }

      if (parsedPlayers.length === 0) {
        throw new Error('No valid players could be parsed from the file.');
      }

      // Automatically tag top 10 players as marquee if none were tagged
      const sortedByRating = [...parsedPlayers].sort((a, b) => b.rating - a.rating);
      const marqueeThreshold = sortedByRating[Math.min(12, sortedByRating.length - 1)]?.rating || 90;
      
      const finalizedPlayers = parsedPlayers.map(p => ({
        ...p,
        isMarquee: p.isMarquee || (p.rating >= marqueeThreshold && p.basePrice >= 1.0)
      }));

      onPlayersParsed(finalizedPlayers);
      setSuccess(`Successfully imported ${finalizedPlayers.length} players!`);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'Failed to parse CSV file. Please check format.');
      setSuccess(null);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (file.name.endsWith('.csv')) {
        const reader = new FileReader();
        reader.onload = (event) => {
          if (event.target?.result) {
            parseCsvContent(event.target.result as string);
          }
        };
        reader.readAsText(file);
      } else {
        setError('Only CSV files are supported.');
      }
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      const reader = new FileReader();
      reader.onload = (event) => {
        if (event.target?.result) {
          parseCsvContent(event.target.result as string);
        }
      };
      reader.readAsText(file);
    }
  };

  return (
    <div className="bg-slate-950/80 border border-cyan-500/20 shadow-[0_0_20px_rgba(6,182,212,0.03)] rounded-xl p-5 mb-6" id="csv-uploader-section">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-xs font-mono font-bold text-cyan-400 uppercase tracking-widest flex items-center gap-2">
          <FileText className="w-4 h-4 text-cyan-400" />
          Auction Database
        </h3>
        <span className="text-[10px] text-slate-400 bg-slate-900 px-2.5 py-1 rounded font-mono font-bold border border-cyan-500/10">
          CURRENT POOL: <strong className="text-cyan-400 font-mono">{playerCount}</strong> PLAYERS
        </span>
      </div>

      <div
        className={`border-2 border-dashed rounded-lg p-5 flex flex-col items-center justify-center transition-all ${
          dragActive 
            ? 'border-cyan-500 bg-cyan-950/10' 
            : 'border-slate-800 hover:border-cyan-500/20 bg-slate-900/40'
        }`}
        onDragEnter={handleDrag}
        onDragOver={handleDrag}
        onDragLeave={handleDrag}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
        style={{ cursor: 'pointer' }}
        id="csv-drag-zone"
      >
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept=".csv"
          onChange={handleChange}
        />
        <div className="bg-slate-950 p-3 rounded-full border border-cyan-500/20 mb-3 text-cyan-400 group-hover:scale-105 transition-transform">
          <Upload className="w-5 h-5 text-cyan-400" />
        </div>
        <p className="text-xs font-bold text-slate-200 text-center uppercase tracking-wider">
          Drag & drop player CSV here, or <span className="text-cyan-400 underline">browse files</span>
        </p>
        <p className="text-[10px] text-slate-500 mt-1.5 text-center font-mono">
          Required Headers: <code className="text-slate-400 bg-slate-950 px-1 py-0.5 rounded border border-slate-850">Player Name</code>, <code className="text-slate-400 bg-slate-950 px-1 py-0.5 rounded border border-slate-850">Base Price (in Crores)</code>, <code className="text-slate-400 bg-slate-950 px-1 py-0.5 rounded border border-slate-850">Primary Role</code>
        </p>
      </div>

      {error && (
        <div className="mt-4 p-3 bg-rose-950/20 border border-rose-900/50 rounded-lg flex items-start gap-2.5 text-rose-200 text-xs">
          <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
          <div>
            <p className="font-bold uppercase tracking-wide text-rose-300">CSV Import Failed</p>
            <p className="text-slate-400 mt-0.5 text-[11px] leading-normal">{error}</p>
          </div>
        </div>
      )}

      {success && (
        <div className="mt-4 p-3 bg-cyan-950/20 border border-cyan-900/50 rounded-lg flex items-start gap-2.5 text-cyan-200 text-xs animate-fade-in">
          <CheckCircle className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
          <div>
            <p className="font-bold uppercase tracking-wide text-cyan-300">Import Successful</p>
            <p className="text-slate-400 mt-0.5 text-[11px] leading-normal">{success}</p>
          </div>
        </div>
      )}
    </div>
  );
}
