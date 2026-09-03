import { useState, useEffect, useRef } from 'react';
import { Player, Team, BiddingLog as LogType, AuctionSetType, PlayerBidInfo } from './types';
import { DEFAULT_PLAYERS } from './data/defaultPlayers';
import { INITIAL_TEAMS } from './data/defaultTeams';

// Components
import CsvUploader from './components/CsvUploader';
import Leaderboard from './components/Leaderboard';
import BiddingLog from './components/BiddingLog';
import SquadModal from './components/SquadModal';
import Confetti from './components/Confetti';

// Icons
import { 
  Play, Pause, Award, RotateCcw, AlertTriangle, ChevronRight, 
  User, CheckCircle, Flame, Shield, Users, Coins, HelpCircle, Star, Search, PlusCircle, Trophy, ShoppingBag
} from 'lucide-react';

export default function App() {
  // --- Game Lifecycle States ---
  const [players, setPlayers] = useState<Player[]>(DEFAULT_PLAYERS);
  const [teams, setTeams] = useState<Team[]>(INITIAL_TEAMS);
  const [userTeamId, setUserTeamId] = useState<string | null>(null);
  
  // 'SETUP' | 'SET_SELECTION' | 'AUCTION_STAGE' | 'NOMINATION' | 'BOOST_ROUND' | 'COMPLETED'
  const [phase, setPhase] = useState<'SETUP' | 'SET_SELECTION' | 'AUCTION_STAGE' | 'NOMINATION' | 'BOOST_ROUND' | 'COMPLETED'>('SETUP');
  
  // --- Active Auction Session States ---
  const [activeSet, setActiveSet] = useState<AuctionSetType>('Marquee');
  const [activePlayerIndex, setActivePlayerIndex] = useState<number>(0);
  const [currentBid, setCurrentBid] = useState<number>(0);
  const [currentBidderId, setCurrentBidderId] = useState<string | null>(null);
  
  // 'WAITING' | 'BIDDING' | 'GOING_ONCE' | 'GOING_TWICE' | 'SOLD' | 'UNSOLD'
  const [biddingStatus, setBiddingStatus] = useState<'WAITING' | 'BIDDING' | 'GOING_ONCE' | 'GOING_TWICE' | 'SOLD' | 'UNSOLD'>('WAITING');
  
  const [biddingLogs, setBiddingLogs] = useState<LogType[]>([]);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [openingCountdown, setOpeningCountdown] = useState<number>(12);
  const [aiOpeningSecond, setAiOpeningSecond] = useState<number | null>(null);
  const [unsoldPool, setUnsoldPool] = useState<Player[]>([]);
  const [nominatedIds, setNominatedIds] = useState<string[]>([]);
  const [boostQueue, setBoostQueue] = useState<Player[]>([]);
  const [completedSets, setCompletedSets] = useState<AuctionSetType[]>([]);
  
  // --- Interactivity / Modals ---
  const [inspectedTeam, setInspectedTeam] = useState<Team | null>(null);
  const [showConfetti, setShowConfetti] = useState<boolean>(false);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [isAutoPilot, setIsAutoPilot] = useState<boolean>(false);
  
  // --- Timer References for Bidding Simulation ---
  const biddingTimerRef = useRef<NodeJS.Timeout | null>(null);
  const countdownTimerRef = useRef<NodeJS.Timeout | null>(null);

  // --- Helper: Get Sorted List of Unique Sets ---
  const getUniqueSets = (): string[] => {
    const csvSets = Array.from(new Set(players.map(p => p.set).filter(Boolean))) as string[];
    
    const parseSetName = (name: string) => {
      const upper = name.toUpperCase().trim();
      
      // Check if marquee
      const isMarquee = upper.startsWith('M') || upper.includes('MARQUEE');
      
      // Extract round number (any digits in the set name)
      const numMatch = upper.match(/\d+/);
      const roundNum = numMatch ? parseInt(numMatch[0], 10) : 1; // Default to 1 if no number
      
      // Determine category priority based on prefix
      let categoryPriority = 7;
      if (upper.startsWith('BA') || upper.startsWith('BAT')) {
        categoryPriority = 1;
      } else if (upper.startsWith('AL') || upper.startsWith('AR') || upper.includes('ROUNDER')) {
        categoryPriority = 2;
      } else if (upper.startsWith('WK') || upper.startsWith('WIC') || upper.includes('KEEPER')) {
        categoryPriority = 3;
      } else if (upper.startsWith('SP') || upper.startsWith('SPI') || upper.includes('SPIN')) {
        categoryPriority = 4;
      } else if (upper.startsWith('FA') || upper.startsWith('FB') || upper.startsWith('FAS') || upper.includes('FAST') || upper.includes('PACE')) {
        categoryPriority = 5;
      } else if (upper.startsWith('UC') || upper.startsWith('UNC') || upper.includes('UNCAPPED')) {
        categoryPriority = 6;
      }
      
      return { isMarquee, roundNum, categoryPriority };
    };

    if (csvSets.length > 0) {
      return csvSets.sort((a, b) => {
        const infoA = parseSetName(a);
        const infoB = parseSetName(b);
        
        // 1. Marquee sets always go first
        if (infoA.isMarquee && !infoB.isMarquee) return -1;
        if (!infoA.isMarquee && infoB.isMarquee) return 1;
        
        if (infoA.isMarquee && infoB.isMarquee) {
          // Both are marquee, sort by round number (M1, M2...)
          if (infoA.roundNum !== infoB.roundNum) {
            return infoA.roundNum - infoB.roundNum;
          }
          return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
        }
        
        // 2. Non-marquee sets: sort primarily by round number
        if (infoA.roundNum !== infoB.roundNum) {
          return infoA.roundNum - infoB.roundNum;
        }
        
        // 3. Same round: sort by category priority
        if (infoA.categoryPriority !== infoB.categoryPriority) {
          return infoA.categoryPriority - infoB.categoryPriority;
        }
        
        // 4. fallback to alphabetical
        return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
      });
    }
    // Default sets sorted in the requested order
    return ['Marquee', 'Batsman', 'All-Rounder', 'Wicketkeeper', 'Spin Bowler', 'Fast Bowler', 'Uncapped'];
  };

  // --- Helper: Categorize Players into Sets ---
  const getPlayersBySet = (set: AuctionSetType): Player[] => {
    if (set === 'Unsold Pool') return unsoldPool;
    
    // If we have custom sets defined on players, filter by player.set
    const hasCustomSets = players.some(p => p.set);
    if (hasCustomSets) {
      return players.filter(p => p.set === set);
    }
    
    if (set === 'Marquee') return players.filter(p => p.isMarquee);
    
    // If set is Uncapped, return non-marquee players who are uncapped
    if (set === 'Uncapped') {
      return players.filter(p => !p.isMarquee && p.status === 'Uncapped');
    }
    
    // For normal role-based sets, return non-marquee, capped players of that role
    return players.filter(p => !p.isMarquee && p.status !== 'Uncapped' && p.role === set);
  };

  const activeSetPlayers = getPlayersBySet(activeSet);
  const currentPlayer: Player | undefined = activeSetPlayers[activePlayerIndex];

  // --- Start Bidding on Active Player ---
  const handleStartBidding = () => {
    if (!currentPlayer) return;
    setBiddingStatus('BIDDING');
    setCurrentBid(0);
    setCurrentBidderId(null);
    setBiddingLogs([
      {
        id: `system-start-${Date.now()}`,
        teamId: 'system',
        teamName: 'Bidding Opened',
        amount: currentPlayer.basePrice,
        timestamp: new Date().toLocaleTimeString()
      }
    ]);
  };

  // --- Fetch the Next Valid Bidding Increment ---
  const getNextBid = (bid: number, basePrice: number): number => {
    if (bid === 0) return basePrice;
    if (bid < 2.0) return parseFloat((bid + 0.20).toFixed(2));
    if (bid < 5.0) return parseFloat((bid + 0.50).toFixed(2));
    return parseFloat((bid + 1.00).toFixed(2));
  };

  // --- Valuation Calculator for AI Strategy ---
  const calculateAIValuation = (team: Team, player: Player, isBoost: boolean = false): number => {
    if (team.squad.length >= 20) return 0;

    // Budget security constraint: Reserve 0.20 Cr for each remaining player slot
    const playersNeeded = 20 - team.squad.length;
    const safetyReserve = (playersNeeded - 1) * 0.20;
    const maxAffordable = team.budget - safetyReserve;
    
    const baseToEvaluate = isBoost ? player.basePrice * 0.5 : player.basePrice;
    if (maxAffordable < baseToEvaluate) return 0;

    // 1. Role preference multiplier
    let roleWeight = 1.0;
    if (player.isMarquee && !isBoost) {
      roleWeight = team.strategy.marqueeWeight;
    } else {
      switch (player.role) {
        case 'Batsman': roleWeight = team.strategy.batsmanWeight; break;
        case 'Wicketkeeper': roleWeight = team.strategy.wicketkeeperWeight; break;
        case 'All-Rounder': roleWeight = team.strategy.allRounderWeight; break;
        case 'Fast Bowler': roleWeight = team.strategy.fastBowlerWeight; break;
        case 'Spin Bowler': roleWeight = team.strategy.spinBowlerWeight; break;
        case 'Uncapped': roleWeight = team.strategy.uncappedWeight; break;
      }
    }

    // 2. Rating Factor (Exponential scale on talent value)
    const ratingFactor = 1.0 + (player.rating - 75) * 0.045;

    // 3. Squad Role Need Urgency mapped to strategist's rules
    const mapping: Record<string, keyof typeof team.strategy.targetRoleCounts> = {
      'Batsman': 'batsman',
      'Wicketkeeper': 'wicketkeeper',
      'All-Rounder': 'allrounder',
      'Fast Bowler': 'bowler',
      'Spin Bowler': 'bowler',
      'Uncapped': 'uncapped'
    };
    const targetKey = mapping[player.role];
    const targetCount = targetKey ? (team.strategy.targetRoleCounts?.[targetKey] || 3) : 3;
    
    let currentCount = 0;
    if (player.role === 'Batsman') currentCount = team.squad.filter(p => p.player.role === 'Batsman').length;
    else if (player.role === 'Wicketkeeper') currentCount = team.squad.filter(p => p.player.role === 'Wicketkeeper').length;
    else if (player.role === 'All-Rounder') currentCount = team.squad.filter(p => p.player.role === 'All-Rounder').length;
    else if (player.role === 'Fast Bowler' || player.role === 'Spin Bowler') currentCount = team.squad.filter(p => p.player.role === 'Fast Bowler' || p.player.role === 'Spin Bowler').length;
    else if (player.role === 'Uncapped') currentCount = team.squad.filter(p => p.player.role === 'Uncapped').length;

    let urgencyFactor = 1.0;
    if (currentCount === 0) {
      urgencyFactor = 1.45; // High priority to get a specialist
    } else if (currentCount < targetCount) {
      urgencyFactor = 1.2; // Still pursuing strategic target
    } else if (currentCount >= targetCount + 2) {
      urgencyFactor = 0.5; // De-prioritize if target is far exceeded
    } else {
      urgencyFactor = 0.8; // Moderately satisfied
    }

    // 4. Budget Aggression Multiplier linked to strategist's ideal budget allocation
    const idealBudgetGroup = targetKey ? (team.strategy.idealBudgetDistribution?.[targetKey] || 15) : 15;
    
    // Calculate how much was already spent on this role
    let roleSpent = 0;
    if (player.role === 'Batsman') roleSpent = team.squad.filter(p => p.player.role === 'Batsman').reduce((sum, b) => sum + b.buyPrice, 0);
    else if (player.role === 'Wicketkeeper') roleSpent = team.squad.filter(p => p.player.role === 'Wicketkeeper').reduce((sum, b) => sum + b.buyPrice, 0);
    else if (player.role === 'All-Rounder') roleSpent = team.squad.filter(p => p.player.role === 'All-Rounder').reduce((sum, b) => sum + b.buyPrice, 0);
    else if (player.role === 'Fast Bowler' || player.role === 'Spin Bowler') roleSpent = team.squad.filter(p => p.player.role === 'Fast Bowler' || p.player.role === 'Spin Bowler').reduce((sum, b) => sum + b.buyPrice, 0);
    else if (player.role === 'Uncapped') roleSpent = team.squad.filter(p => p.player.role === 'Uncapped').reduce((sum, b) => sum + b.buyPrice, 0);

    let budgetAggression = 1.0;
    if (roleSpent >= idealBudgetGroup) {
      budgetAggression = 0.7; // Exceeded budget guideline, bid conservatively
    } else {
      const room = idealBudgetGroup - roleSpent;
      if (room > 12.0 && player.rating >= 85) {
        budgetAggression = 1.25; // Massive headroom, bid aggressively
      }
    }

    const averageWalletSize = team.budget / playersNeeded;
    let walletMultiplier = Math.max(0.75, Math.min(1.75, averageWalletSize / 5.0)) * budgetAggression;

    // If it's the boost/accelerated round, teams with low squad counts are highly desperate
    if (isBoost) {
      if (playersNeeded >= 5) {
        urgencyFactor *= 1.5;
        walletMultiplier *= 1.2;
      } else if (playersNeeded === 1) {
        urgencyFactor *= 0.9; // Just need anyone to finish
      }
    }

    // Combine factors
    let valuation = baseToEvaluate * roleWeight * ratingFactor * urgencyFactor * walletMultiplier;

    // Apply strategic constraints
    valuation = Math.min(valuation, team.strategy.absoluteMaxBid);
    valuation = Math.min(valuation, maxAffordable);

    // Punjab early bargain filter
    if (team.id === 'punjab' && team.squad.length < 10 && !isBoost) {
      const cap = player.basePrice * (team.strategy.conservativeThreshold || 1.45);
      valuation = Math.min(valuation, cap);
    }

    return parseFloat(valuation.toFixed(2));
  };

  // --- Place a Bid ---
  const placeBid = (teamId: string, amount: number) => {
    const team = teams.find(t => t.id === teamId);
    if (!team) return;

    const isOpeningBid = currentBid === 0;

    setCurrentBid(amount);
    setCurrentBidderId(teamId);
    setBiddingStatus('BIDDING');

    setBiddingLogs(prev => {
      const logs = [...prev];
      if (isOpeningBid) {
        logs.push({
          id: `system-start-${Date.now()}`,
          teamId: 'system',
          teamName: 'Bidding Opened',
          amount: amount,
          timestamp: new Date().toLocaleTimeString()
        });
      }
      logs.push({
        id: `bid-${Date.now()}-${Math.random()}`,
        teamId,
        teamName: team.name,
        amount,
        timestamp: new Date().toLocaleTimeString()
      });
      return logs;
    });
  };

  // --- Raise Paddle (User Bid Entrypoint) ---
  const handleRaisePaddle = () => {
    if (!currentPlayer || biddingStatus === 'SOLD' || biddingStatus === 'UNSOLD') return;

    const userTeam = teams.find(t => t.id === userTeamId);
    if (!userTeam) return;

    if (userTeam.squad.length >= 20) {
      alert('Your roster is already full with 20 players!');
      return;
    }

    const isForeign = currentPlayer.country && currentPlayer.country.trim().toLowerCase() !== 'india';
    if (isForeign) {
      const foreignCount = userTeam.squad.filter(s => s.player.country && s.player.country.trim().toLowerCase() !== 'india').length;
      if (foreignCount >= 8) {
        alert('STRICT RULE VIOLATION: Your team already has 8 foreign players! Each franchise is strictly limited to a maximum of 8 foreign players.');
        return;
      }
    }

    const isBoost = phase === 'BOOST_ROUND';
    const playerBasePrice = isBoost ? currentPlayer.basePrice * 0.5 : currentPlayer.basePrice;
    const nextBidAmount = getNextBid(currentBid, playerBasePrice);

    // Budget security constraint
    const requiredReserve = (20 - userTeam.squad.length - 1) * 0.20;
    if (userTeam.budget - nextBidAmount < requiredReserve) {
      alert(`Violation of Budget Safety Margin! You must retain at least ${requiredReserve.toFixed(2)} Cr to afford the remaining players in your 20-player squad.`);
      return;
    }

    if (currentBidderId === userTeamId) {
      alert('You already hold the leading bid!');
      return;
    }

    placeBid(userTeamId!, nextBidAmount);
  };

  // --- Drop Out / Pass ---
  const handlePass = () => {
    if (biddingStatus !== 'BIDDING' && biddingStatus !== 'GOING_ONCE' && biddingStatus !== 'GOING_TWICE') return;
    
    // Speed up countdown if the user passes and doesn't want to bid
    if (currentBidderId !== userTeamId) {
      setBiddingStatus('GOING_ONCE');
    }
  };

  // --- Complete Sale / Declare Sold or Unsold ---
  const finalizeBidProcess = () => {
    if (!currentPlayer) return;

    if (!currentBidderId) {
      // Unsold
      setBiddingStatus('UNSOLD');
      setUnsoldPool(prev => [...prev, currentPlayer]);
      setBiddingLogs(prev => [
        ...prev,
        {
          id: `system-unsold-${Date.now()}`,
          teamId: 'unsold',
          teamName: 'UNSOLD',
          amount: 0,
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
    } else {
      // Sold
      const winnerId = currentBidderId;
      const finalPrice = currentBid;

      setTeams(prevTeams => 
        prevTeams.map(t => {
          if (t.id === winnerId) {
            return {
              ...t,
              budget: parseFloat((t.budget - finalPrice).toFixed(2)),
              squad: [...t.squad, { player: currentPlayer, buyPrice: finalPrice }]
            };
          }
          return t;
        })
      );

      const winningTeam = teams.find(t => t.id === winnerId);
      setBiddingStatus('SOLD');
      setShowConfetti(true);

      setBiddingLogs(prev => [
        ...prev,
        {
          id: `system-sold-${Date.now()}`,
          teamId: 'sold',
          teamName: `SOLD to ${winningTeam?.name} for ${finalPrice.toFixed(2)} Cr!`,
          amount: finalPrice,
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
    }
  };

  // --- Simulation Game Loop ---
  useEffect(() => {
    if (isPaused || phase === 'SETUP' || phase === 'SET_SELECTION' || phase === 'COMPLETED' || phase === 'NOMINATION') return;
    if (biddingStatus === 'WAITING' || biddingStatus === 'SOLD' || biddingStatus === 'UNSOLD') return;

    // AI evaluate state
    const isBoost = phase === 'BOOST_ROUND';
    const nextBidAmount = getNextBid(currentBid, isBoost ? currentPlayer.basePrice * 0.5 : currentPlayer.basePrice);

    // Find all AI franchises that want and are eligible to bid
    const eligibleBidders = teams.filter(t => {
      if (t.isHuman) return false;
      if (t.id === currentBidderId) return false; // Cannot outbid self
      if (t.squad.length >= 20) return false;

      // Strict Foreign Limit Check: Max 8 foreign players per team
      const isForeign = currentPlayer.country && currentPlayer.country.trim().toLowerCase() !== 'india';
      if (isForeign) {
        const foreignCount = t.squad.filter(s => s.player.country && s.player.country.trim().toLowerCase() !== 'india').length;
        if (foreignCount >= 8) return false;
      }

      // Budget Security Check
      const reserve = (20 - t.squad.length - 1) * 0.20;
      if (t.budget - nextBidAmount < reserve) return false;

      // Strategic valuation matching
      const valuation = calculateAIValuation(t, currentPlayer, isBoost);
      return valuation >= nextBidAmount;
    });

    if (eligibleBidders.length > 0) {
      // AI bid trigger
      biddingTimerRef.current = setTimeout(() => {
        // Randomly select weighted on valuation surplus to keep it natural
        const sortedBidders = eligibleBidders.sort((a, b) => {
          const valA = calculateAIValuation(a, currentPlayer, isBoost);
          const valB = calculateAIValuation(b, currentPlayer, isBoost);
          return valB - valA;
        });
        
        const leadingBidder = sortedBidders[0];
        placeBid(leadingBidder.id, nextBidAmount);
      }, 1000 + Math.random() * 800); // 1.0s to 1.8s delay
    } else {
      // Countdown progress if nobody bids
      countdownTimerRef.current = setTimeout(() => {
        if (biddingStatus === 'BIDDING') {
          setBiddingStatus('GOING_ONCE');
        } else if (biddingStatus === 'GOING_ONCE') {
          setBiddingStatus('GOING_TWICE');
        } else if (biddingStatus === 'GOING_TWICE') {
          finalizeBidProcess();
        }
      }, 1800); // 1.8 seconds per countdown step
    }

    return () => {
      if (biddingTimerRef.current) clearTimeout(biddingTimerRef.current);
      if (countdownTimerRef.current) clearTimeout(countdownTimerRef.current);
    };
  }, [biddingStatus, currentBid, currentBidderId, isPaused, teams, phase]);

  // --- Clean Confetti overlay ---
  useEffect(() => {
    if (showConfetti) {
      const timer = setTimeout(() => setShowConfetti(false), 4500);
      return () => clearTimeout(timer);
    }
  }, [showConfetti]);

  // --- Opening Countdown Reset ---
  useEffect(() => {
    if (biddingStatus === 'WAITING' && currentPlayer) {
      setOpeningCountdown(12);
      // AI opening bid second can be a random second between 3 and 10 (giving user 2-3 seconds to bid first)
      const randomSecond = Math.floor(Math.random() * 8) + 3; // 3 to 10
      setAiOpeningSecond(randomSecond);
    }
  }, [currentPlayer?.id, biddingStatus]);

  // --- Opening Countdown Simulation Tick ---
  useEffect(() => {
    if (isPaused || phase === 'SETUP' || phase === 'SET_SELECTION' || phase === 'COMPLETED' || phase === 'NOMINATION') return;
    if (biddingStatus !== 'WAITING' || !currentPlayer) return;

    const isBoost = phase === 'BOOST_ROUND';
    const playerBasePrice = isBoost ? currentPlayer.basePrice * 0.5 : currentPlayer.basePrice;

    const timer = setInterval(() => {
      setOpeningCountdown((prev) => {
        const nextCount = prev - 1;
        
        // If countdown reaches 0, player goes UNSOLD
        if (nextCount <= 0) {
          clearInterval(timer);
          finalizeBidProcess(); // currentBidderId is null, currentBid is 0, so marks as unsold
          return 0;
        }

        // If it matches the AI opening bid second, let's see if an AI wants to bid
        if (nextCount === aiOpeningSecond) {
          // Check if any AI wants to bid
          const eligibleBidders = teams.filter(t => {
            if (t.isHuman) return false;
            if (t.squad.length >= 20) return false;

            const isForeign = currentPlayer.country && currentPlayer.country.trim().toLowerCase() !== 'india';
            if (isForeign) {
              const foreignCount = t.squad.filter(s => s.player.country && s.player.country.trim().toLowerCase() !== 'india').length;
              if (foreignCount >= 8) return false;
            }

            const reserve = (20 - t.squad.length - 1) * 0.20;
            if (t.budget - playerBasePrice < reserve) return false;

            const valuation = calculateAIValuation(t, currentPlayer, isBoost);
            return valuation >= playerBasePrice;
          });

          if (eligibleBidders.length > 0) {
            // Sort by valuation to find who wants him most
            const sortedBidders = eligibleBidders.sort((a, b) => {
              const valA = calculateAIValuation(a, currentPlayer, isBoost);
              const valB = calculateAIValuation(b, currentPlayer, isBoost);
              return valB - valA;
            });
            const opener = sortedBidders[0];
            clearInterval(timer);
            placeBid(opener.id, playerBasePrice);
          }
        }

        return nextCount;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [biddingStatus, currentPlayer, isPaused, aiOpeningSecond, teams, phase]);

  // --- Auto-Simulate Current Player Instantly ---
  const handleAutoSimulatePlayer = () => {
    if (!currentPlayer || ['SOLD', 'UNSOLD'].includes(biddingStatus)) return;

    const isBoost = phase === 'BOOST_ROUND';
    const playerBasePrice = isBoost ? currentPlayer.basePrice * 0.5 : currentPlayer.basePrice;

    // We will simulate the bidding locally and then apply the final state
    let simBid = 0;
    let simBidderId: string | null = null;
    let simLogs: LogType[] = [];

    // Step 1: Opening bid
    const eligibleOpeners = teams.filter(t => {
      if (t.isHuman) return false;
      if (t.squad.length >= 20) return false;

      const isForeign = currentPlayer.country && currentPlayer.country.trim().toLowerCase() !== 'india';
      if (isForeign) {
        const foreignCount = t.squad.filter(s => s.player.country && s.player.country.trim().toLowerCase() !== 'india').length;
        if (foreignCount >= 8) return false;
      }

      const reserve = (20 - t.squad.length - 1) * 0.20;
      if (t.budget - playerBasePrice < reserve) return false;

      const valuation = calculateAIValuation(t, currentPlayer, isBoost);
      return valuation >= playerBasePrice;
    });

    if (eligibleOpeners.length > 0) {
      // Find team with highest valuation to open
      const sortedOpeners = [...eligibleOpeners].sort((a, b) => {
        const valA = calculateAIValuation(a, currentPlayer, isBoost);
        const valB = calculateAIValuation(b, currentPlayer, isBoost);
        return valB - valA;
      });
      const opener = sortedOpeners[0];
      simBid = playerBasePrice;
      simBidderId = opener.id;

      simLogs.push({
        id: `sim-start-${Date.now()}`,
        teamId: 'system',
        teamName: 'Bidding Opened',
        amount: simBid,
        timestamp: new Date().toLocaleTimeString()
      });

      simLogs.push({
        id: `sim-bid-opener-${Date.now()}`,
        teamId: opener.id,
        teamName: opener.name,
        amount: simBid,
        timestamp: new Date().toLocaleTimeString()
      });

      // Now run the bidding loop
      let activeWar = true;
      let iterations = 0;
      while (activeWar && iterations < 50) {
        iterations++;
        const nextBidAmount = getNextBid(simBid, playerBasePrice);

        // Find eligible bidders at this next bid level
        const eligibleBidders = teams.filter(t => {
          if (t.isHuman) return false;
          if (t.id === simBidderId) return false;
          if (t.squad.length >= 20) return false;

          const isForeign = currentPlayer.country && currentPlayer.country.trim().toLowerCase() !== 'india';
          if (isForeign) {
            const foreignCount = t.squad.filter(s => s.player.country && s.player.country.trim().toLowerCase() !== 'india').length;
            if (foreignCount >= 8) return false;
          }

          const reserve = (20 - t.squad.length - 1) * 0.20;
          if (t.budget - nextBidAmount < reserve) return false;

          const valuation = calculateAIValuation(t, currentPlayer, isBoost);
          return valuation >= nextBidAmount;
        });

        if (eligibleBidders.length > 0) {
          const sortedBidders = [...eligibleBidders].sort((a, b) => {
            const valA = calculateAIValuation(a, currentPlayer, isBoost);
            const valB = calculateAIValuation(b, currentPlayer, isBoost);
            return valB - valA;
          });
          const nextBidder = sortedBidders[0];
          simBid = nextBidAmount;
          simBidderId = nextBidder.id;

          simLogs.push({
            id: `sim-bid-${Date.now()}-${iterations}`,
            teamId: nextBidder.id,
            teamName: nextBidder.name,
            amount: simBid,
            timestamp: new Date().toLocaleTimeString()
          });
        } else {
          activeWar = false;
        }
      }
    }

    // Finalize the simulated result
    if (!simBidderId) {
      setBiddingStatus('UNSOLD');
      setUnsoldPool(prev => [...prev, currentPlayer]);
      setBiddingLogs([
        {
          id: `system-unsold-${Date.now()}`,
          teamId: 'unsold',
          teamName: 'UNSOLD',
          amount: 0,
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
      setCurrentBid(0);
      setCurrentBidderId(null);
    } else {
      const winnerId = simBidderId;
      const finalPrice = simBid;
      const winningTeam = teams.find(t => t.id === winnerId);

      setTeams(prevTeams => 
        prevTeams.map(t => {
          if (t.id === winnerId) {
            return {
              ...t,
              budget: parseFloat((t.budget - finalPrice).toFixed(2)),
              squad: [...t.squad, { player: currentPlayer, buyPrice: finalPrice }]
            };
          }
          return t;
        })
      );

      setBiddingStatus('SOLD');
      setShowConfetti(true);
      setCurrentBid(finalPrice);
      setCurrentBidderId(winnerId);
      setBiddingLogs([
        ...simLogs,
        {
          id: `system-sold-${Date.now()}`,
          teamId: 'sold',
          teamName: `SOLD to ${winningTeam?.name} for ${finalPrice.toFixed(2)} Cr!`,
          amount: finalPrice,
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
    }
  };

  // --- Auto Pilot / Continuous Simulation Loop ---
  useEffect(() => {
    if (!isAutoPilot || isPaused || phase === 'SETUP' || phase === 'SET_SELECTION' || phase === 'COMPLETED' || phase === 'NOMINATION') return;

    let timer: NodeJS.Timeout;

    if (biddingStatus === 'WAITING') {
      // Auto-simulate current player after a brief 1.2 second pause so user sees them
      timer = setTimeout(() => {
        handleAutoSimulatePlayer();
      }, 1200);
    } else if (['SOLD', 'UNSOLD'].includes(biddingStatus)) {
      // Auto-load next player after a brief 2.2 second pause to read the bid results
      timer = setTimeout(() => {
        if (phase === 'BOOST_ROUND') {
          handleNextBoostPlayer();
        } else {
          handleNextPlayer();
        }
      }, 2200);
    }

    return () => clearTimeout(timer);
  }, [isAutoPilot, biddingStatus, currentPlayer?.id, isPaused, phase]);

  // --- Setup user's selection ---
  const handleSelectTeam = (teamId: string) => {
    setUserTeamId(teamId);
    setTeams(prev => prev.map(t => ({ ...t, isHuman: t.id === teamId })));
  };

  const handleStartGame = () => {
    if (!userTeamId) {
      alert('Please select an IPL franchise to manage!');
      return;
    }
    setPhase('SET_SELECTION');
  };

  // --- Navigate sets ---
  const handleOpenSet = (set: AuctionSetType) => {
    setActiveSet(set);
    setActivePlayerIndex(0);
    setBiddingStatus('WAITING');
    setCurrentBid(0);
    setCurrentBidderId(null);
    setBiddingLogs([]);
    setPhase('AUCTION_STAGE');
  };

  // --- Complete Active Player and Move Forward ---
  const handleNextPlayer = () => {
    const nextIdx = activePlayerIndex + 1;
    if (nextIdx < activeSetPlayers.length) {
      setActivePlayerIndex(nextIdx);
      setBiddingStatus('WAITING');
      setCurrentBid(0);
      setCurrentBidderId(null);
      setBiddingLogs([]);
    } else {
      // Completed active set!
      const nextCompleted = [...completedSets, activeSet];
      setCompletedSets(nextCompleted);

      // Check if all primary sets are finished
      const allSets = getUniqueSets();
      const finishedAll = allSets.every(s => nextCompleted.includes(s));

      if (finishedAll) {
        // Shift to nomination phase for unsold pool
        setPhase('NOMINATION');
        setActiveSet('Unsold Pool');
      } else {
        setPhase('SET_SELECTION');
      }
    }
  };

  // --- Nomination Phase for Boost Accelerated Round ---
  const handleToggleNomination = (playerId: string) => {
    if (nominatedIds.includes(playerId)) {
      setNominatedIds(prev => prev.filter(id => id !== playerId));
    } else {
      if (nominatedIds.length >= 5) {
        alert('You can only nominate a maximum of 5 players!');
        return;
      }
      setNominatedIds(prev => [...prev, playerId]);
    }
  };

  const handleLaunchBoostRound = () => {
    // Generate AI nominations based on their roster gaps
    const aiNominations: Player[] = [];
    
    teams.forEach(t => {
      if (t.isHuman) return;
      const squadDeficit = 20 - t.squad.length;
      if (squadDeficit > 0) {
        // Nominate unsold players of roles they need
        const neededRoles: Player['role'][] = [];
        const roleDistribution = {
          'Batsman': t.squad.filter(p => p.player.role === 'Batsman').length,
          'Wicketkeeper': t.squad.filter(p => p.player.role === 'Wicketkeeper').length,
          'All-Rounder': t.squad.filter(p => p.player.role === 'All-Rounder').length,
          'Fast Bowler': t.squad.filter(p => p.player.role === 'Fast Bowler').length,
          'Spin Bowler': t.squad.filter(p => p.player.role === 'Spin Bowler').length,
        };

        if (roleDistribution.Wicketkeeper === 0) neededRoles.push('Wicketkeeper');
        if (roleDistribution.Batsman < 3) neededRoles.push('Batsman');
        if (roleDistribution['All-Rounder'] < 2) neededRoles.push('All-Rounder');
        if (roleDistribution['Fast Bowler'] < 3) neededRoles.push('Fast Bowler');
        if (roleDistribution['Spin Bowler'] < 2) neededRoles.push('Spin Bowler');

        // Sample players matching needed role from unsold pool
        const matchingUnsold = unsoldPool.filter(p => 
          (neededRoles.length === 0 || neededRoles.includes(p.role)) && 
          !nominatedIds.includes(p.id) &&
          !aiNominations.some(ap => ap.id === p.id)
        );

        // Pick up to 3 to nominate
        const sliceCount = Math.min(3, matchingUnsold.length);
        const selected = matchingUnsold.slice(0, sliceCount);
        aiNominations.push(...selected);
      }
    });

    // Merge User + AI nominations
    const userNoms = unsoldPool.filter(p => nominatedIds.includes(p.id));
    const fullBoostPool = [...userNoms, ...aiNominations];

    if (fullBoostPool.length === 0) {
      // In case nobody was nominated, just grab first 10 unsold
      const fallbackNoms = unsoldPool.slice(0, 8);
      setBoostQueue(fallbackNoms);
    } else {
      setBoostQueue(fullBoostPool);
    }

    setPhase('BOOST_ROUND');
    setActiveSet('Unsold Pool');
    setActivePlayerIndex(0);
    setBiddingStatus('WAITING');
    setCurrentBid(0);
    setCurrentBidderId(null);
    setBiddingLogs([]);
  };

  // --- Complete Boost Player and Progress ---
  const handleNextBoostPlayer = () => {
    const nextIdx = activePlayerIndex + 1;
    if (nextIdx < boostQueue.length) {
      setActivePlayerIndex(nextIdx);
      setBiddingStatus('WAITING');
      setCurrentBid(0);
      setCurrentBidderId(null);
      setBiddingLogs([]);
    } else {
      // Finished Boost Round!
      // To satisfy constraint "Exactly 20 players must be signed", we run a self-healing rapid draft filler
      // for any teams that are still short of 20 players.
      autoDraftSquadFillers();
    }
  };

  // --- Guarantee exactly 20 players signed by the end of simulation ---
  const autoDraftSquadFillers = () => {
    let currentUnsoldPool = [...unsoldPool].filter(p => 
      !boostQueue.some(bq => bq.id === p.id) || 
      // check if they were bought
      !teams.some(t => t.squad.some(s => s.player.id === p.id))
    );

    setTeams(prevTeams => {
      return prevTeams.map(team => {
        let teamSquad = [...team.squad];
        let teamPurse = team.budget;
        const slotsNeeded = 20 - teamSquad.length;

        if (slotsNeeded > 0) {
          // Pull cheapest fallback players to reach 20
          for (let i = 0; i < slotsNeeded; i++) {
            const foreignCount = teamSquad.filter(s => s.player.country && s.player.country.trim().toLowerCase() !== 'india').length;
            const draftedIdx = currentUnsoldPool.findIndex(p => {
              const isPForeign = p.country && p.country.trim().toLowerCase() !== 'india';
              if (isPForeign && foreignCount >= 8) return false;
              return true;
            });

            if (draftedIdx !== -1) {
              const draftedPlayer = currentUnsoldPool.splice(draftedIdx, 1)[0];
              const purchasePrice = Math.min(draftedPlayer.basePrice, teamPurse);
              teamSquad.push({
                player: draftedPlayer,
                buyPrice: purchasePrice
              });
              teamPurse = parseFloat((teamPurse - purchasePrice).toFixed(2));
            } else {
              // Emergency mock fallback if unsold pool is entirely depleted
              const dummyPlayer: Player = {
                id: `emergency-${team.id}-${i}-${Date.now()}`,
                name: `${team.shortName} Academy Prospect ${i + 1}`,
                basePrice: 0.20,
                role: 'Uncapped',
                status: 'Uncapped',
                rating: 74,
                isMarquee: false,
                country: 'India'
              };
              teamSquad.push({
                player: dummyPlayer,
                buyPrice: 0.20
              });
              teamPurse = parseFloat((teamPurse - 0.20).toFixed(2));
            }
          }
        }

        return {
          ...team,
          squad: teamSquad,
          budget: teamPurse
        };
      });
    });

    setPhase('COMPLETED');
  };

  // --- Reset Simulator ---
  const handleResetGame = () => {
    setPlayers(DEFAULT_PLAYERS);
    setTeams(INITIAL_TEAMS);
    setUserTeamId(null);
    setPhase('SETUP');
    setActiveSet('Marquee');
    setActivePlayerIndex(0);
    setCurrentBid(0);
    setCurrentBidderId(null);
    setBiddingStatus('WAITING');
    setBiddingLogs([]);
    setUnsoldPool([]);
    setNominatedIds([]);
    setBoostQueue([]);
    setCompletedSets([]);
    setInspectedTeam(null);
  };

  // --- Stats and Awards for Completed Screen ---
  const getCompletedStats = () => {
    // 1. Champion Builder (Highest sum of ratings in squad)
    const evaluatedTeams = teams.map(t => {
      const totalRating = t.squad.reduce((sum, b) => sum + b.player.rating, 0);
      const avgRating = totalRating / 20;
      const spent = parseFloat((100.0 - t.budget).toFixed(2));
      return { team: t, totalRating, avgRating, spent };
    });

    const sortedByRosterPower = [...evaluatedTeams].sort((a, b) => b.totalRating - a.totalRating);
    const champion = sortedByRosterPower[0];

    // 2. Record Signing (Costliest buy of the auction)
    let costliestBuy: { player: Player; teamName: string; price: number } | null = null;
    teams.forEach(t => {
      t.squad.forEach(b => {
        if (!costliestBuy || b.buyPrice > costliestBuy.price) {
          costliestBuy = { player: b.player, teamName: t.name, price: b.buyPrice };
        }
      });
    });

    // 3. Best Value Steal (Highly rated bought for cheap base price)
    let valueSteal: { player: Player; teamName: string; price: number; ratingDiff: number } | null = null;
    teams.forEach(t => {
      t.squad.forEach(b => {
        // Look for rating / price ratio
        const valueScore = b.player.rating - (b.buyPrice * 2.5);
        if (!valueSteal || valueScore > (valueSteal.player.rating - (valueSteal.price * 2.5))) {
          valueSteal = { player: b.player, teamName: t.name, price: b.buyPrice, ratingDiff: valueScore };
        }
      });
    });

    return {
      champion,
      costliestBuy,
      valueSteal,
      sortedByRosterPower
    };
  };

  const finalStats = phase === 'COMPLETED' ? getCompletedStats() : null;

  return (
    <div className="min-h-screen bg-[#020617] text-slate-100 font-sans selection:bg-cyan-500 selection:text-slate-950 flex flex-col relative overflow-hidden">
      {/* Visual background elements */}
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
            Auction Simulator <span className="text-rose-500 animate-pulse font-bold ml-2">● LIVE</span>
          </div>
        </div>

        <div className="flex items-center gap-6">
          {phase !== 'SETUP' && (
            <div className="hidden md:flex gap-8 text-xs font-semibold uppercase tracking-wider">
              <div className="flex flex-col items-end leading-none">
                <span className="text-slate-500 text-[9px] uppercase tracking-widest font-bold">Active Set</span>
                <span className="text-cyan-300 mt-1">{activeSet} Players</span>
              </div>
              <div className="flex flex-col items-end leading-none">
                <span className="text-slate-500 text-[9px] uppercase tracking-widest font-bold">Remaining</span>
                <span className="text-cyan-300 mt-1">
                  {phase === 'BOOST_ROUND' ? boostQueue.length - activePlayerIndex : activeSetPlayers.length - activePlayerIndex} / {phase === 'BOOST_ROUND' ? boostQueue.length : activeSetPlayers.length}
                </span>
              </div>
            </div>
          )}

          {phase !== 'SETUP' && (
            <button 
              onClick={handleResetGame}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-slate-900 hover:bg-slate-800 border border-cyan-500/20 hover:border-cyan-500/50 text-[11px] font-bold text-cyan-300 uppercase tracking-widest transition-all cursor-pointer"
              id="reset-simulation-btn"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Reset Engine
            </button>
          )}
        </div>
      </header>

      {/* --- MAIN LAYOUT WINDOW --- */}
      <main className="flex-1 w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex flex-col relative z-10 min-h-0">
        
        {/* ========================================= */}
        {/* PHASE 1: GAME SETUP                       */}
        {/* ========================================= */}
        {phase === 'SETUP' && (
          <div className="flex-1 flex flex-col gap-8 animate-fade-in" id="setup-view">
            <div className="text-center max-w-2xl mx-auto space-y-3 py-6">
              <span className="text-cyan-400 font-mono text-xs font-bold bg-cyan-950/40 border border-cyan-500/30 px-3 py-1 rounded uppercase tracking-widest">
                VIVO IPL MOCK AUCTION 2026
              </span>
              <h2 className="text-3xl md:text-4xl font-display font-extrabold text-white tracking-tight leading-none uppercase">
                Championships are Built in the Auction Room
              </h2>
              <p className="text-slate-400 text-xs md:text-sm leading-relaxed">
                Take the hotseat. Choose your IPL team and build a 20-player match-winning roster with a strict 100 Crore budget. Compete against 9 aggressive AI strategies modeled on real franchises.
              </p>
            </div>

            {/* CSV UPLOADER PANEL */}
            <CsvUploader 
              onPlayersParsed={(parsed) => {
                setPlayers(parsed);
                const customSets = Array.from(new Set(parsed.map(p => p.set).filter(Boolean))) as string[];
                if (customSets.length > 0) {
                  const sorted = customSets.sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }));
                  setActiveSet(sorted[0]);
                } else {
                  setActiveSet('Marquee');
                }
                setActivePlayerIndex(0);
                setCompletedSets([]);
                setUnsoldPool([]);
                setBiddingStatus('WAITING');
                setCurrentBid(0);
                setCurrentBidderId(null);
                setBiddingLogs([]);
              }} 
              playerCount={players.length} 
            />

            {/* FRANCHISE SELECTION GRID */}
            <div className="space-y-4">
              <h3 className="font-display font-extrabold text-xs uppercase tracking-widest text-cyan-400 flex items-center gap-2">
                <span className="w-1.5 h-3 bg-cyan-500 rounded-sm"></span>
                Select Your Franchise
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-3.5">
                {teams.map((t) => {
                  const isSelected = userTeamId === t.id;
                  return (
                    <button
                      key={t.id}
                      onClick={() => handleSelectTeam(t.id)}
                      className={`relative border-2 rounded-xl p-4 text-left transition-all overflow-hidden flex flex-col justify-between group h-[160px] cursor-pointer shadow-lg ${
                        isSelected 
                          ? 'border-cyan-400 bg-cyan-950/20 ring-2 ring-cyan-500/20' 
                          : 'border-slate-800 hover:border-cyan-500/20 bg-slate-900/60'
                      }`}
                      id={`setup-select-team-${t.id}`}
                    >
                      {/* Colored gradient overlay */}
                      <div className={`absolute top-0 right-0 w-24 h-24 rounded-full blur-2xl opacity-10 transition-opacity group-hover:opacity-20 ${t.logo}`} />
                      
                      <div className="flex items-start justify-between">
                        <div className={`w-10 h-10 rounded flex items-center justify-center text-slate-950 font-black text-xs skew-x-[-6deg] shadow-md border border-white/10 ${t.logo}`}>
                          {t.shortName}
                        </div>
                        {isSelected && (
                          <span className="bg-cyan-500 text-slate-950 text-[8px] font-bold px-2 py-0.5 rounded uppercase tracking-wider font-mono">
                            MANAGER
                          </span>
                        )}
                      </div>

                      <div className="mt-4">
                        <p className="font-bold text-white text-sm uppercase tracking-tight group-hover:text-cyan-400 transition-colors">{t.name}</p>
                        <p className="text-[10px] text-slate-500 mt-1 line-clamp-2 leading-normal">{t.strategy.description}</p>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* ACTION BUTTON */}
            <div className="flex justify-center pt-4">
              <button
                onClick={handleStartGame}
                disabled={!userTeamId}
                className={`flex items-center gap-2.5 px-10 py-4 rounded-xl text-xs font-black uppercase tracking-widest transition-all duration-300 shadow-xl cursor-pointer ${
                  userTeamId 
                    ? 'bg-cyan-500 hover:bg-cyan-400 text-slate-950 scale-100 hover:scale-[1.02] active:scale-95 shadow-[0_0_20px_rgba(34,211,238,0.3)]' 
                    : 'bg-slate-800 text-slate-500 cursor-not-allowed opacity-60'
                }`}
                id="launch-auction-arena-btn"
              >
                <Play className="w-3.5 h-3.5 fill-current" />
                LAUNCH AUCTION ARENA
              </button>
            </div>
          </div>
        )}

        {/* ========================================= */}
        {/* PHASE 2: SET SELECTION PANEL              */}
        {/* ========================================= */}
        {phase === 'SET_SELECTION' && (
          <div className="flex-1 flex flex-col gap-6 max-w-4xl mx-auto w-full animate-fade-in" id="set-selection-view">
            <div className="text-center space-y-2 py-4">
              <span className="text-cyan-400 font-mono text-xs font-bold bg-cyan-950/40 border border-cyan-500/30 px-3 py-1 rounded uppercase tracking-widest">
                STAGE SELECTION
              </span>
              <h2 className="text-2xl font-display font-extrabold text-white uppercase">Select Next Auction Set</h2>
              <p className="text-slate-400 text-xs">Franchises will enter bidding set by set. Choose which players to auction next.</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              {/* Left Column: List of Sets */}
              <div className="space-y-3">
                <h3 className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest font-mono">Available Sets</h3>
                <div className="space-y-2.5">
                  {(() => {
                    const allSets = getUniqueSets();
                    const hasCustomSets = players.some(p => p.set);
                    const firstIncompleteSet = allSets.find(s => !completedSets.includes(s));

                    return allSets.map((setName) => {
                      const isCompleted = completedSets.includes(setName);
                      const playerCount = getPlayersBySet(setName).length;
                      
                      // For custom sets, strict round-by-round sequential progression
                      const isDisabled = hasCustomSets 
                        ? (setName !== firstIncompleteSet || isCompleted || playerCount === 0)
                        : (isCompleted || playerCount === 0);

                      let title = setName;
                      let desc = `Bidding round for set ${setName}`;
                      let icon = '🏏';

                      if (!hasCustomSets) {
                        const defaultInfo = {
                          'Marquee': { title: 'Marquee Players', desc: 'Elite tournament superstars', icon: '💎' },
                          'Batsman': { title: 'Batsmen', desc: 'Top-order & middle-order batting specialists', icon: '🏏' },
                          'Wicketkeeper': { title: 'Wicketkeepers', desc: 'Glovework and aggressive finishers', icon: '🧤' },
                          'All-Rounder': { title: 'All-Rounders', desc: 'Versatile utilities who bat and bowl', icon: '🔄' },
                          'Fast Bowler': { title: 'Fast Bowlers', desc: 'Express seamers and swing masters', icon: '⚡' },
                          'Spin Bowler': { title: 'Spin Bowlers', desc: 'Mystery spinners and turn experts', icon: '🌀' },
                          'Uncapped': { title: 'Uncapped Players', desc: 'Young domestic talents & budget prospects', icon: '🌱' },
                        }[setName] || { title: setName, desc: 'Bidding round', icon: '🏏' };
                        title = defaultInfo.title;
                        desc = defaultInfo.desc;
                        icon = defaultInfo.icon;
                      } else {
                        title = `Round ${setName}`;
                        desc = `Bidding round for players in Set ${setName}`;
                        icon = '📦';
                        if (setName.toUpperCase().startsWith('M')) {
                          icon = '💎';
                        }
                      }

                      return (
                        <button
                          key={setName}
                          onClick={() => !isCompleted && handleOpenSet(setName)}
                          disabled={isDisabled}
                          className={`w-full text-left p-3.5 rounded-xl border flex items-center justify-between transition-all ${
                            isCompleted
                              ? 'bg-slate-900/15 border-emerald-500/15 text-emerald-500/50 cursor-not-allowed'
                              : isDisabled
                                ? 'bg-slate-950/20 border-slate-900 text-slate-600 cursor-not-allowed opacity-50'
                                : 'bg-slate-900/50 hover:bg-slate-800/80 border-cyan-500/20 hover:border-cyan-400 hover:scale-[1.01] active:scale-[0.99] cursor-pointer text-slate-100 shadow-[0_0_15px_rgba(34,211,238,0.02)]'
                          }`}
                          id={`select-set-btn-${setName}`}
                        >
                          <div className="flex items-center gap-3">
                            <span className="text-xl">{icon}</span>
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="font-bold text-xs uppercase tracking-wider">{title}</span>
                                {isCompleted && (
                                  <span className="bg-emerald-950/40 text-emerald-400 border border-emerald-500/30 text-[8px] font-bold px-1.5 py-0.5 rounded font-mono">
                                    COMPLETED
                                  </span>
                                )}
                                {hasCustomSets && !isCompleted && setName === firstIncompleteSet && (
                                  <span className="bg-cyan-950/40 text-cyan-400 border border-cyan-500/30 text-[8px] font-bold px-1.5 py-0.5 rounded font-mono animate-pulse">
                                    ACTIVE ROUND
                                  </span>
                                )}
                              </div>
                              <span className="text-[10px] text-slate-500 mt-0.5 block leading-normal">{desc}</span>
                            </div>
                          </div>

                          <div className="text-right flex flex-col items-end">
                            <span className="text-xs font-mono font-bold text-cyan-400">
                              {playerCount} <span className="text-[9px] text-slate-500 font-normal">players</span>
                            </span>
                          </div>
                        </button>
                      );
                    });
                  })()}
                </div>
              </div>

              {/* Right Column: User's Franchise Dashboard */}
              <div className="bg-slate-950/80 border border-cyan-500/20 shadow-[0_0_30px_rgba(6,182,212,0.05)] rounded-2xl p-5 flex flex-col justify-between">
                <div>
                  <h3 className="text-[10px] font-bold text-cyan-400 uppercase tracking-widest font-mono mb-4">Your Franchise</h3>
                  {(() => {
                    const myTeam = teams.find(t => t.id === userTeamId);
                    if (!myTeam) return null;
                    return (
                      <div className="space-y-5">
                        <div className="flex items-center gap-3">
                          <div className={`w-12 h-12 rounded flex items-center justify-center text-slate-950 font-black text-lg skew-x-[-6deg] shadow-lg border border-white/10 ${myTeam.logo}`}>
                            {myTeam.shortName}
                          </div>
                          <div>
                            <h4 className="font-bold text-white text-base uppercase tracking-tight">{myTeam.name}</h4>
                            <p className="text-[10px] text-slate-500 font-mono uppercase tracking-wider mt-0.5">{myTeam.strategy.name} Style</p>
                          </div>
                        </div>

                        {/* Roster stats */}
                        <div className="grid grid-cols-2 gap-3 pt-2 font-mono">
                          <div className="bg-slate-900/40 p-3 rounded-xl border border-cyan-500/10">
                            <span className="text-[9px] text-slate-500 block uppercase tracking-wider">REMAINING PURSE</span>
                            <span className="text-cyan-400 font-black text-sm flex items-center gap-1 mt-1">
                              <Coins className="w-4 h-4 text-cyan-400" />
                              {myTeam.budget.toFixed(2)} CR
                            </span>
                          </div>
                          <div className="bg-slate-900/40 p-3 rounded-xl border border-cyan-500/10">
                            <span className="text-[9px] text-slate-500 block uppercase tracking-wider">SQUAD SIZE</span>
                            <span className="text-cyan-300 font-black text-sm flex items-center gap-1 mt-1">
                              <Users className="w-4 h-4 text-cyan-300" />
                              {myTeam.squad.length} / 20
                            </span>
                          </div>
                        </div>

                        {/* Checklist of roster slots filled */}
                        <div className="pt-2">
                          <p className="text-[10px] text-slate-500 uppercase tracking-wider font-mono font-bold mb-2">Roster Balance Checklist:</p>
                          <div className="grid grid-cols-2 gap-2 text-xs">
                            <span className="flex items-center gap-1.5 text-slate-300">
                              <span className={`w-1.5 h-1.5 rounded-full ${myTeam.squad.filter(p => p.player.role === 'Batsman').length >= 3 ? 'bg-cyan-400 shadow-[0_0_6px_rgba(34,211,238,0.5)]' : 'bg-rose-500/50'}`} />
                              Batsmen ({myTeam.squad.filter(p => p.player.role === 'Batsman').length}/3 min)
                            </span>
                            <span className="flex items-center gap-1.5 text-slate-300">
                              <span className={`w-1.5 h-1.5 rounded-full ${myTeam.squad.filter(p => p.player.role === 'Wicketkeeper').length >= 1 ? 'bg-cyan-400 shadow-[0_0_6px_rgba(34,211,238,0.5)]' : 'bg-rose-500/50'}`} />
                              Keepers ({myTeam.squad.filter(p => p.player.role === 'Wicketkeeper').length}/1 min)
                            </span>
                            <span className="flex items-center gap-1.5 text-slate-300">
                              <span className={`w-1.5 h-1.5 rounded-full ${myTeam.squad.filter(p => p.player.role === 'All-Rounder').length >= 2 ? 'bg-cyan-400 shadow-[0_0_6px_rgba(34,211,238,0.5)]' : 'bg-rose-500/50'}`} />
                              All-Rounders ({myTeam.squad.filter(p => p.player.role === 'All-Rounder').length}/2 min)
                            </span>
                            <span className="flex items-center gap-1.5 text-slate-300">
                              <span className={`w-1.5 h-1.5 rounded-full ${myTeam.squad.filter(p => p.player.role === 'Fast Bowler' || p.player.role === 'Spin Bowler').length >= 4 ? 'bg-cyan-400 shadow-[0_0_6px_rgba(34,211,238,0.5)]' : 'bg-rose-500/50'}`} />
                              Bowlers ({myTeam.squad.filter(p => p.player.role === 'Fast Bowler' || p.player.role === 'Spin Bowler').length}/4 min)
                            </span>
                          </div>
                        </div>
                      </div>
                    );
                  })()}
                </div>

                <div className="pt-5 border-t border-cyan-500/10 mt-6 text-slate-400 text-[11px] leading-relaxed flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 text-cyan-400 shrink-0" />
                  <span>Each team is strictly required to sign exactly <strong>20 players</strong> total. Choose a role-specific set to open up bidding and bolster your team's squad count!</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ========================================= */}
        {/* PHASE 3: MAIN AUCTION BLOCK (ARENA)       */}
        {/* ========================================= */}
        {(phase === 'AUCTION_STAGE' || phase === 'BOOST_ROUND') && (
          <div className="flex-1 flex flex-col md:grid md:grid-cols-12 gap-5 min-h-0 animate-scale-up" id="auction-stage-view">
            
            {/* LEFT LEADERBOARD PANEL (3 Cols) */}
            <div className="md:col-span-3 h-[400px] md:h-full min-h-0">
              <Leaderboard 
                teams={teams} 
                userTeamId={userTeamId!} 
                activeBidderId={currentBidderId} 
                onTeamClick={(team) => setInspectedTeam(team)}
              />
            </div>

            {/* CENTER AUCTION CARD (6 Cols) */}
            <div className="md:col-span-6 flex flex-col gap-4">
              
              {/* STAGE HEADER (Active progress) */}
              <div className="bg-slate-900 border border-cyan-500/20 shadow-[0_0_15px_rgba(6,182,212,0.03)] rounded-xl px-4 py-3 flex items-center justify-between">
                <div>
                  <span className="text-[10px] text-cyan-400 font-mono font-bold tracking-widest uppercase block">
                    {phase === 'BOOST_ROUND' ? 'ACCELERATED BOOST AUCTION (50% OFF)' : `${activeSet.toUpperCase()} SET`}
                  </span>
                  <p className="font-extrabold text-white text-xs uppercase tracking-tight mt-0.5">
                    Player {activePlayerIndex + 1} of {phase === 'BOOST_ROUND' ? boostQueue.length : activeSetPlayers.length}
                  </p>
                </div>
                
                <div className="flex items-center gap-2">
                  {/* Autopilot Toggle Button */}
                  <button
                    onClick={() => setIsAutoPilot(!isAutoPilot)}
                    className={`text-[10px] uppercase tracking-widest px-3 py-1.5 rounded font-bold font-mono transition-all cursor-pointer flex items-center gap-1.5 ${
                      isAutoPilot 
                        ? 'bg-purple-600 border border-purple-400 text-white shadow-[0_0_12px_rgba(168,85,247,0.5)] scale-[1.02]'
                        : 'bg-slate-950 hover:bg-slate-900 border border-purple-500/20 hover:border-purple-500/50 text-purple-400 hover:text-purple-300'
                    }`}
                    title="Toggle continuous automated simulation of all remaining players"
                  >
                    {isAutoPilot ? (
                      <>
                        <span className="w-1.5 h-1.5 rounded-full bg-white animate-ping shrink-0" />
                        <span>🤖 AUTOPILOT ON</span>
                      </>
                    ) : (
                      <>
                        <span>🤖 AUTOPILOT OFF</span>
                      </>
                    )}
                  </button>

                  {/* Normal Pause Button if not waiting/sold/unsold */}
                  {!['WAITING', 'SOLD', 'UNSOLD'].includes(biddingStatus) && (
                    <button 
                      onClick={() => setIsPaused(!isPaused)}
                      className="bg-slate-950 hover:bg-slate-800 border border-cyan-500/20 hover:border-cyan-400 p-1.5 rounded text-cyan-400 hover:text-white transition-all cursor-pointer"
                      id="pause-simulation-btn"
                      title={isPaused ? "Resume Auction Simulation" : "Pause Auction Simulation"}
                    >
                      {isPaused ? <Play className="w-3.5 h-3.5 fill-current" /> : <Pause className="w-3.5 h-3.5 fill-current" />}
                    </button>
                  )}

                  {['WAITING', 'SOLD', 'UNSOLD'].includes(biddingStatus) ? (
                    <span className="text-[10px] uppercase tracking-wider bg-slate-950 border border-slate-850 px-3 py-1.5 rounded font-bold font-mono text-slate-500">
                      Block Closed
                    </span>
                  ) : (
                    <span className="text-[9px] uppercase tracking-widest bg-cyan-500/10 border border-cyan-500/30 px-3 py-1.5 rounded font-bold font-mono text-cyan-400 flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-ping" />
                      SIM ACTIVE
                    </span>
                  )}
                </div>
              </div>

              {/* CORE AUCTION DISPATCH CARD */}
              {currentPlayer ? (
                <div className="bg-slate-950/70 border-2 border-cyan-500/30 shadow-[0_0_50px_rgba(34,211,238,0.12)] rounded-2xl overflow-hidden flex-1 flex flex-col justify-between relative" id="auction-stage-card">
                  
                  {/* Glowing background representing bidding temperature */}
                  {biddingStatus !== 'WAITING' && biddingStatus !== 'SOLD' && biddingStatus !== 'UNSOLD' && (
                    <div className={`absolute top-0 inset-x-0 h-[3px] transition-all duration-300 ${
                      biddingStatus === 'GOING_ONCE' 
                        ? 'bg-amber-400 animate-pulse' 
                        : biddingStatus === 'GOING_TWICE' 
                          ? 'bg-rose-500 animate-pulse' 
                          : 'bg-cyan-500'
                    }`} />
                  )}

                  <div className="p-6 flex flex-col md:flex-row gap-5 flex-1 items-center">
                    
                    {/* Visual Player Avatar Frame */}
                    <div className="w-24 h-24 md:w-28 md:h-28 rounded-xl bg-slate-900 border border-cyan-500/20 flex flex-col items-center justify-center shrink-0 relative shadow-inner">
                      {/* Rating Badge */}
                      <div className="absolute top-1.5 right-1.5 bg-cyan-500/10 border border-cyan-500/20 px-1.5 py-0.5 rounded text-[9px] font-mono font-bold text-cyan-400">
                        ★ {currentPlayer.rating}
                      </div>
                      
                      <span className="text-2xl">👤</span>
                      <span className="text-[9px] font-mono font-bold text-slate-500 mt-2 uppercase tracking-wider">{currentPlayer.status}</span>
                    </div>

                    {/* Player Specs */}
                    <div className="flex-1 text-center md:text-left space-y-2">
                      <div className="flex flex-col md:flex-row md:items-center gap-2">
                        <h3 className="font-display font-extrabold text-xl text-white uppercase tracking-tight">
                          {currentPlayer.name}
                        </h3>
                      </div>
                      
                      <div className="flex flex-wrap items-center justify-center md:justify-start gap-1.5 text-[10px] font-mono uppercase">
                        <span className="bg-slate-900 border border-slate-800 px-2 py-0.5 rounded text-slate-400">
                          {currentPlayer.role}
                        </span>
                        <span className="bg-slate-900 border border-slate-800 px-2 py-0.5 rounded text-slate-400">
                          {currentPlayer.country || 'India'}
                        </span>
                      </div>

                      <div className="pt-1.5 flex items-center justify-center md:justify-start gap-4">
                        <div className="text-left leading-none">
                          <span className="text-[9px] text-slate-500 block font-mono font-bold uppercase tracking-widest">BASE PRICE</span>
                          <span className="text-cyan-400 font-extrabold font-mono text-sm block mt-1">
                            {phase === 'BOOST_ROUND' 
                              ? `${(currentPlayer.basePrice * 0.5).toFixed(2)} CR` 
                              : `${currentPlayer.basePrice.toFixed(2)} CR`
                            }
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* ACTIVE LIVE BIDDING SCOREBOARD */}
                  <div className="px-6 py-6 border-y border-cyan-500/10 bg-slate-900/40 flex flex-col items-center justify-center gap-4 text-center">
                    {biddingStatus === 'WAITING' ? (
                      <div className="space-y-4 py-2 w-full flex flex-col items-center">
                        <div className="flex flex-col items-center gap-1.5 animate-pulse">
                          <span className="text-[10px] font-mono font-bold text-cyan-400 tracking-widest uppercase bg-cyan-500/10 border border-cyan-500/20 px-3 py-1 rounded-full">
                            Awaiting Opening Bid
                          </span>
                          <span className="text-4xl font-black text-white font-mono tracking-tighter mt-1 block">
                            {openingCountdown}s
                          </span>
                        </div>
                        
                        <div className="w-full max-w-xs bg-slate-950 rounded-lg p-1 border border-cyan-500/10">
                          <div 
                            className="h-1.5 bg-cyan-500 rounded-md transition-all duration-1000 ease-linear" 
                            style={{ width: `${(openingCountdown / 12) * 100}%` }}
                          />
                        </div>

                        <p className="text-[11px] text-slate-400 max-w-sm leading-normal">
                          Raise your paddle or wait for another franchise to open the bidding at base price of <strong className="text-cyan-300 font-bold">{(phase === 'BOOST_ROUND' ? currentPlayer.basePrice * 0.5 : currentPlayer.basePrice).toFixed(2)} Cr</strong>.
                        </p>
                      </div>
                    ) : biddingStatus === 'SOLD' ? (
                      <div className="space-y-2 py-2 animate-scale-up">
                        <span className="bg-cyan-500/15 border border-cyan-500/30 text-cyan-400 font-bold font-mono text-xs px-3 py-1 rounded uppercase tracking-widest">
                          SOLD!
                        </span>
                        <h4 className="text-white font-extrabold text-base uppercase tracking-tight mt-1">
                          {teams.find(t => t.id === currentBidderId)?.name}
                        </h4>
                        <p className="text-rose-500 font-black font-mono text-2xl md:text-3xl tracking-tighter uppercase">
                          {currentBid.toFixed(2)} CR
                        </p>
                      </div>
                    ) : biddingStatus === 'UNSOLD' ? (
                      <div className="space-y-2 py-2 text-center">
                        <span className="bg-rose-500/15 border border-rose-500/30 text-rose-400 font-bold font-mono text-xs px-3 py-1 rounded uppercase tracking-widest">
                          UNSOLD
                        </span>
                        <p className="text-slate-500 text-xs mt-1 leading-normal">Player remains unacquired. Passed to Accelerated Pool.</p>
                      </div>
                    ) : (
                      // Realtime active bidding war dashboard
                      <div className="w-full flex flex-col items-center gap-3">
                        <div className="flex flex-col items-center gap-1 animate-pulse">
                          {biddingStatus === 'GOING_ONCE' && (
                            <span className="text-[10px] font-mono font-bold text-amber-400 tracking-widest uppercase bg-amber-400/10 border border-amber-400/20 px-3 py-0.5 rounded">
                              Going once...
                            </span>
                          )}
                          {biddingStatus === 'GOING_TWICE' && (
                            <span className="text-[10px] font-mono font-bold text-rose-400 tracking-widest uppercase bg-rose-500/10 border border-rose-500/20 px-3 py-0.5 rounded animate-bounce">
                              Going twice...
                            </span>
                          )}
                          {biddingStatus === 'BIDDING' && (
                            <span className="text-[10px] font-mono font-bold text-cyan-400 tracking-widest uppercase bg-cyan-500/10 border border-cyan-500/20 px-3 py-0.5 rounded">
                              Active War
                            </span>
                          )}
                        </div>

                        <div className="space-y-1">
                          <span className="text-[9px] text-slate-500 font-mono tracking-widest block uppercase font-bold">LEADING BID</span>
                          <span className="text-3xl md:text-4xl font-black text-rose-500 font-mono tracking-tighter block uppercase">
                            {currentBid === 0 ? '---' : `${currentBid.toFixed(2)} CR`}
                          </span>
                        </div>

                        {currentBidderId && (
                          <div className="flex items-center gap-2">
                            <span className="text-[9px] text-slate-500 font-mono uppercase font-bold">Held by</span>
                            <span className="text-xs font-extrabold text-cyan-300 bg-slate-900 border border-cyan-500/20 px-3 py-1.5 rounded uppercase tracking-wider">
                              {teams.find(t => t.id === currentBidderId)?.name}
                            </span>
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* USER BID CONTROLS BAR */}
                  <div className="p-4 bg-slate-950 border-t border-cyan-500/10 flex items-center justify-between gap-3">
                    {['SOLD', 'UNSOLD'].includes(biddingStatus) ? (
                      <button
                        onClick={phase === 'BOOST_ROUND' ? handleNextBoostPlayer : handleNextPlayer}
                        className="px-6 py-3.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-black text-xs tracking-widest uppercase transition-all cursor-pointer flex items-center justify-center gap-2 w-full shadow-[0_0_15px_rgba(34,211,238,0.2)]"
                        id="next-auction-player-btn"
                      >
                        {phase === 'BOOST_ROUND' && activePlayerIndex + 1 === boostQueue.length ? (
                          <>
                            <span>COMPLETE TOURNAMENT SQUAD DRAFT</span>
                            <ChevronRight className="w-4 h-4 text-slate-950 shrink-0" />
                          </>
                        ) : activePlayerIndex + 1 === activeSetPlayers.length ? (
                          <>
                            <span>CONCLUDE SET AND VIEW STANDINGS</span>
                            <ChevronRight className="w-4 h-4 text-slate-950 shrink-0" />
                          </>
                        ) : (
                          <>
                            <span>NEXT PLAYER ON BLOCK</span>
                            <ChevronRight className="w-4 h-4 text-slate-950 shrink-0" />
                          </>
                        )}
                      </button>
                    ) : (
                      <div className="grid grid-cols-3 gap-3 w-full">
                        <button
                          onClick={handlePass}
                          disabled={biddingStatus === 'WAITING' || currentBidderId === userTeamId}
                          className={`px-3 py-3.5 rounded-lg font-bold text-xs uppercase tracking-wider transition-all cursor-pointer ${
                            biddingStatus === 'WAITING' || currentBidderId === userTeamId 
                              ? 'bg-slate-900 border border-slate-850 text-slate-600 cursor-not-allowed' 
                              : 'bg-slate-900 hover:bg-slate-800 border border-slate-850 text-slate-400 hover:text-slate-300'
                          }`}
                          id="paddle-pass-btn"
                        >
                          PASS / DECLINE
                        </button>
                        
                        <button
                          onClick={handleAutoSimulatePlayer}
                          className="px-3 py-3.5 rounded-lg bg-indigo-950 hover:bg-indigo-900 border border-indigo-500/30 hover:border-indigo-400 text-indigo-300 hover:text-white font-extrabold text-xs uppercase tracking-wider transition-all cursor-pointer flex flex-col items-center justify-center leading-none"
                          id="paddle-auto-sim-btn"
                          title="Simulate all AI bids for this player instantly"
                        >
                          <span>⚡ AUTO-SIM</span>
                          <span className="text-[7px] font-mono opacity-70 block mt-1 text-center">INSTANT SKIP</span>
                        </button>

                        <button
                          onClick={handleRaisePaddle}
                          disabled={currentBidderId === userTeamId}
                          className={`px-3 py-3.5 rounded-lg font-black text-xs tracking-widest uppercase transition-all cursor-pointer shadow-lg flex flex-col items-center justify-center leading-none ${
                            currentBidderId === userTeamId
                              ? 'bg-slate-900 border border-slate-850 text-slate-600 cursor-not-allowed'
                              : 'bg-cyan-500 text-slate-950 hover:bg-cyan-400 shadow-[0_0_15px_rgba(34,211,238,0.2)] hover:scale-[1.01]'
                          }`}
                          id="paddle-bid-btn"
                        >
                          <span>{biddingStatus === 'WAITING' ? 'OPEN BIDDING' : 'RAISE PADDLE'}</span>
                          <span className="text-[8px] font-mono opacity-80 block mt-1 text-center font-bold">
                            {biddingStatus === 'WAITING' 
                              ? (phase === 'BOOST_ROUND' ? currentPlayer.basePrice * 0.5 : currentPlayer.basePrice).toFixed(2)
                              : getNextBid(currentBid, phase === 'BOOST_ROUND' ? currentPlayer.basePrice * 0.5 : currentPlayer.basePrice).toFixed(2)
                            } CR
                          </span>
                        </button>
                      </div>
                    )}
                  </div>

                </div>
              ) : (
                <div className="bg-slate-950/40 border-2 border-cyan-500/20 rounded-2xl p-10 text-center text-slate-500 flex flex-col items-center justify-center flex-1">
                  <AlertTriangle className="w-12 h-12 text-cyan-400 mb-3 animate-pulse" />
                  <p className="font-mono text-xs uppercase">Error: No player selected. Something went wrong with queue parsing.</p>
                </div>
              )}
            </div>

            {/* RIGHT LIVE BID LOG PANEL (3 Cols) */}
            <div className="md:col-span-3 h-[400px] md:h-full min-h-0">
              <BiddingLog logs={biddingLogs} teams={teams} />
            </div>

          </div>
        )}

        {/* ========================================= */}
        {/* PHASE 4: NOMINATION / ACCELERATED SETUP   */}
        {/* ========================================= */}
        {phase === 'NOMINATION' && (
          <div className="flex-1 flex flex-col gap-6 animate-scale-up" id="nomination-view">
            <div className="text-center max-w-2xl mx-auto space-y-2 py-4">
              <span className="text-cyan-400 font-mono text-xs font-bold bg-cyan-950/40 border border-cyan-500/30 px-3 py-1 rounded uppercase tracking-widest">
                ACCELERATED PREPARATION ROUND
              </span>
              <h2 className="text-2xl md:text-3xl font-display font-extrabold text-white uppercase tracking-tight">Nominate Unsold Players for the Boost Round</h2>
              <p className="text-slate-400 text-xs leading-normal">
                All primary auction pools have been completed. Nominate up to <strong>5 players</strong> from the Unsold Pool below to bring them back to the block at a rapid-fire <strong>50% discount</strong> on their base price.
              </p>
            </div>

            {unsoldPool.length === 0 ? (
              <div className="bg-slate-950/50 border border-cyan-500/20 rounded-2xl p-12 text-center text-slate-400 flex flex-col items-center justify-center max-w-md mx-auto space-y-4 shadow-[0_0_30px_rgba(6,182,212,0.05)]">
                <CheckCircle className="w-12 h-12 text-cyan-400" />
                <div>
                  <h3 className="font-extrabold text-white text-base uppercase tracking-tight">Perfect Main Round!</h3>
                  <p className="text-xs text-slate-500 mt-1">Every single player on the auction block was bought! There are no unsold players left.</p>
                </div>
                <button
                  onClick={autoDraftSquadFillers}
                  className="px-6 py-3.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 text-xs font-black tracking-widest uppercase shadow-[0_0_15px_rgba(34,211,238,0.2)] cursor-pointer"
                  id="skip-to-end-no-unsold-btn"
                >
                  CONCLUDE AUCTION SIMULATOR
                </button>
              </div>
            ) : (
              <div className="flex-1 flex flex-col gap-4 min-h-0">
                {/* Master list container */}
                <div className="bg-slate-950/60 border border-cyan-500/20 shadow-[0_0_30px_rgba(6,182,212,0.05)] rounded-xl overflow-hidden flex-1 flex flex-col min-h-[400px]">
                  
                  {/* Filter and stats banner */}
                  <div className="p-4 bg-slate-900 border-b border-cyan-500/10 flex flex-wrap items-center justify-between gap-3 text-xs font-mono font-bold">
                    <span className="text-slate-400">
                      TOTAL UNSOLD POOL: <strong className="text-cyan-400">{unsoldPool.length}</strong> PLAYERS
                    </span>
                    <span className="text-cyan-400 uppercase tracking-wider">
                      YOUR NOMINATIONS: <strong className="text-slate-100">{nominatedIds.length} / 5</strong>
                    </span>
                  </div>

                  {/* Scroller grid */}
                  <div className="p-4 overflow-y-auto grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3.5 flex-1 custom-scrollbar">
                    {unsoldPool.map((p) => {
                      const isNominated = nominatedIds.includes(p.id);
                      return (
                        <button
                          key={p.id}
                          onClick={() => handleToggleNomination(p.id)}
                          className={`p-3.5 rounded-xl border text-left flex items-center justify-between gap-3 transition-all cursor-pointer relative group ${
                            isNominated 
                              ? 'border-cyan-400 bg-cyan-950/20 ring-1 ring-cyan-500/20' 
                              : 'border-slate-800 hover:border-cyan-500/20 bg-slate-950/40'
                          }`}
                          id={`nominate-player-card-${p.id}`}
                        >
                          <div className="min-w-0">
                            <p className="font-bold text-xs uppercase tracking-tight text-slate-200 group-hover:text-cyan-400 truncate transition-colors">
                              {p.name}
                            </p>
                            <span className="text-[10px] text-slate-500 font-mono mt-1 block">
                              ★ {p.rating} • {p.role}
                            </span>
                          </div>

                          <div className="text-right shrink-0">
                            <span className="text-[9px] text-slate-500 font-mono block font-bold">BASE PRICE</span>
                            <span className="text-cyan-400 font-bold font-mono text-xs block">
                              {p.basePrice.toFixed(2)} CR
                            </span>
                          </div>

                          {/* Plus sign overlay */}
                          <div className="absolute top-2 right-2 text-cyan-400 opacity-0 group-hover:opacity-100 transition-opacity">
                            <PlusCircle className="w-4 h-4 fill-current text-cyan-500" />
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Launch accelerator round action bar */}
                <div className="flex justify-center pt-3">
                  <button
                    onClick={handleLaunchBoostRound}
                    className="flex items-center gap-2.5 px-8 py-4 rounded-xl text-xs font-black uppercase tracking-widest bg-cyan-500 hover:bg-cyan-400 text-slate-950 transition-all scale-100 hover:scale-[1.01] shadow-[0_0_20px_rgba(34,211,238,0.3)] cursor-pointer"
                    id="launch-boost-round-btn"
                  >
                    <Flame className="w-3.5 h-3.5 fill-current" />
                    LAUNCH RAPID-FIRE BOOST AUCTION
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ========================================= */}
        {/* PHASE 5: COMPLETED CONGRATULATIONS PAGE   */}
        {/* ========================================= */}
        {phase === 'COMPLETED' && finalStats && (
          <div className="flex-1 flex flex-col gap-6 animate-scale-up" id="completed-view">
            
            {/* Visual Confetti Header */}
            <div className="text-center max-w-2xl mx-auto space-y-3 py-6">
              <span className="text-amber-400 font-mono text-xs font-bold bg-amber-400/10 border border-amber-400/20 px-3 py-1 rounded-full uppercase tracking-wider">
                TOURNAMENT AUCTION CONCLUDED
              </span>
              <h2 className="text-3xl md:text-4xl font-display font-black text-white tracking-tight flex items-center justify-center gap-2.5 uppercase">
                <Trophy className="w-8 h-8 text-cyan-400 shrink-0" />
                Roster Complete!
              </h2>
              <p className="text-slate-400 text-xs md:text-sm leading-normal">
                All 10 franchises have satisfied the squad regulations by drafting exactly <strong>20 players</strong>. Let's inspect the auction outcomes and crown the Champion Squad Builder.
              </p>
            </div>

            {/* BIG HIGHLIGHTS / AWARDS BENTO GRID */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              
              {/* CHAMPION BUILDER CARD */}
              <div className="bg-slate-950/80 border border-cyan-500/20 shadow-[0_0_30px_rgba(6,182,212,0.05)] rounded-2xl p-5 flex flex-col justify-between relative overflow-hidden group">
                <div className="absolute top-0 right-0 w-32 h-32 bg-cyan-500/5 rounded-full blur-2xl pointer-events-none" />
                <div>
                  <span className="text-[9px] text-cyan-400 font-mono font-bold tracking-widest uppercase block mb-1">👑 CHAMPION SQUAD BUILDER</span>
                  <div className="flex items-center gap-3.5 mt-2">
                    <div className={`w-12 h-12 rounded flex items-center justify-center text-slate-950 font-black text-lg skew-x-[-6deg] shadow-lg ${finalStats.champion.team.logo}`}>
                      {finalStats.champion.team.shortName}
                    </div>
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

              {/* COSTLIEST RECORD BUY */}
              <div className="bg-slate-950/80 border border-cyan-500/20 shadow-[0_0_30px_rgba(6,182,212,0.05)] rounded-2xl p-5 flex flex-col justify-between relative overflow-hidden">
                <div>
                  <span className="text-[9px] text-rose-400 font-mono font-bold tracking-widest uppercase block mb-1">💰 COSTLIEST ACQUISITION</span>
                  {finalStats.costliestBuy ? (
                    <div className="mt-2 space-y-1">
                      <p className="font-extrabold text-white text-base truncate uppercase tracking-tight">{finalStats.costliestBuy.player.name}</p>
                      <p className="text-xs text-slate-400 font-mono">Bought by <strong className="text-slate-200">{finalStats.costliestBuy.teamName}</strong></p>
                    </div>
                  ) : (
                    <p className="text-slate-500 text-xs italic mt-2">No buys recorded</p>
                  )}
                </div>

                {finalStats.costliestBuy && (
                  <div className="border-t border-cyan-500/10 pt-4 mt-4 text-xs font-mono flex items-center justify-between">
                    <span className="text-slate-400">Player Rating: <strong className="text-cyan-400 font-bold">★ {finalStats.costliestBuy.player.rating}</strong></span>
                    <span className="text-rose-500 font-extrabold">{finalStats.costliestBuy.price.toFixed(2)} CR</span>
                  </div>
                )}
              </div>

              {/* VALUE STEAL BUY */}
              <div className="bg-slate-950/80 border border-cyan-500/20 shadow-[0_0_30px_rgba(6,182,212,0.05)] rounded-2xl p-5 flex flex-col justify-between relative overflow-hidden">
                <div>
                  <span className="text-[9px] text-cyan-400 font-mono font-bold tracking-widest uppercase block mb-1">💎 BEST VALUE STEAL</span>
                  {finalStats.valueSteal ? (
                    <div className="mt-2 space-y-1">
                      <p className="font-extrabold text-white text-base truncate uppercase tracking-tight">{finalStats.valueSteal.player.name}</p>
                      <p className="text-xs text-slate-400 font-mono">Snared by <strong className="text-slate-200">{finalStats.valueSteal.teamName}</strong></p>
                    </div>
                  ) : (
                    <p className="text-slate-500 text-xs italic mt-2">No steals recorded</p>
                  )}
                </div>

                {finalStats.valueSteal && (
                  <div className="border-t border-cyan-500/10 pt-4 mt-4 text-xs font-mono flex items-center justify-between">
                    <span className="text-slate-400">Rating: <strong className="text-cyan-300 font-bold">★ {finalStats.valueSteal.player.rating}</strong></span>
                    <span className="text-cyan-400 font-bold">Bought: {finalStats.valueSteal.price.toFixed(2)} CR</span>
                  </div>
                )}
              </div>

            </div>

            {/* FULL TOURNAMENT STANDINGS & SEARCH BAR */}
            <div className="bg-slate-950/80 border border-cyan-500/20 shadow-[0_0_35px_rgba(6,182,212,0.05)] rounded-2xl p-5 flex-1 flex flex-col min-h-0">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-cyan-500/10">
                <h3 className="font-display font-extrabold text-xs uppercase tracking-widest text-cyan-400 flex items-center gap-2">
                  <span className="w-1.5 h-3 bg-cyan-500 rounded-sm"></span>
                  Final Franchise Power Standings
                </h3>

                {/* Master search block */}
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

              {/* Master scroller leaderboard */}
              <div className="divide-y divide-cyan-500/5 overflow-y-auto flex-1 custom-scrollbar max-h-[360px] pt-2" id="final-standings-list">
                {finalStats.sortedByRosterPower.map((row, idx) => {
                  const isUser = row.team.id === userTeamId;
                  return (
                    <div 
                      key={row.team.id}
                      className="py-3.5 flex flex-col md:flex-row md:items-center justify-between gap-4 px-2 hover:bg-slate-900/40 transition-colors rounded-lg"
                    >
                      <div className="flex items-center gap-3">
                        <span className="text-xs font-mono font-bold text-slate-500 w-4">{idx + 1}</span>
                        <button
                          onClick={() => setInspectedTeam(row.team)}
                          className={`w-9 h-9 rounded flex items-center justify-center text-slate-950 font-black text-xs skew-x-[-6deg] shadow border border-white/5 cursor-pointer ${row.team.logo}`}
                        >
                          {row.team.shortName}
                        </button>
                        <div>
                          <div className="flex items-center gap-1.5">
                            <button 
                              onClick={() => setInspectedTeam(row.team)}
                              className="font-bold text-sm text-slate-100 hover:text-cyan-400 transition-colors text-left uppercase tracking-tight"
                            >
                              {row.team.name}
                            </button>
                            {isUser && (
                              <span className="bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 text-[8px] px-1.5 py-0.5 rounded font-mono font-bold">YOU</span>
                            )}
                          </div>
                          <span className="text-[10px] text-slate-500 font-mono block mt-0.5 uppercase">Manager Strategy: {row.team.strategy.name}</span>
                        </div>
                      </div>

                      <div className="flex items-center gap-6 text-xs font-mono text-slate-400">
                        <div className="text-right">
                          <span className="text-[9px] text-slate-500 block uppercase font-bold">ROSTER SCORE</span>
                          <span className="text-rose-500 font-black text-xs">{row.totalRating} pts</span>
                        </div>
                        <div className="text-right">
                          <span className="text-[9px] text-slate-500 block uppercase font-bold">AVG ATTRIBUTE</span>
                          <span className="text-cyan-300 font-bold text-xs">★ {row.avgRating}</span>
                        </div>
                        <div className="text-right">
                          <span className="text-[9px] text-slate-500 block uppercase font-bold">REMAINING CASH</span>
                          <span className="text-cyan-400 font-bold text-xs">{row.team.budget.toFixed(2)} CR</span>
                        </div>
                        <button
                          onClick={() => setInspectedTeam(row.team)}
                          className="px-3 py-1.5 bg-slate-900 hover:bg-slate-800 border border-cyan-500/20 rounded text-[10px] font-bold text-cyan-400 hover:text-cyan-300 transition-all cursor-pointer uppercase tracking-wider"
                        >
                          View Squad
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Play again button */}
            <div className="flex justify-center pt-2">
              <button
                onClick={handleResetGame}
                className="flex items-center gap-2 px-8 py-3.5 bg-cyan-500 hover:bg-cyan-400 text-slate-950 rounded-lg text-xs font-black uppercase tracking-widest transition-all shadow-[0_0_15px_rgba(34,211,238,0.2)] cursor-pointer"
                id="play-again-completed-btn"
              >
                <RotateCcw className="w-3.5 h-3.5" />
                PLAY AGAIN
              </button>
            </div>
          </div>
        )}

      </main>

      {/* --- SQUAD INSPECTOR MODAL --- */}
      <SquadModal 
        team={inspectedTeam} 
        onClose={() => setInspectedTeam(null)} 
      />
    </div>
  );
}
