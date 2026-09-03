export interface Player {
  id: string;
  name: string;
  basePrice: number; // in Crores, e.g., 2.00
  role: 'Batsman' | 'Wicketkeeper' | 'All-Rounder' | 'Fast Bowler' | 'Spin Bowler' | 'Uncapped';
  status: 'Capped' | 'Uncapped';
  rating: number; // 70 to 99 representing skill level
  isMarquee: boolean;
  imageSeed?: string;
  country?: string;
  set?: string; // e.g., "M1", "M2"
  age?: number;
  battingStyle?: string;
  bowlingStyle?: string;
}

export interface PlayerBidInfo {
  player: Player;
  buyPrice: number; // in Crores
}

export interface AIStrategy {
  name: string;
  description: string;
  marqueeWeight: number;
  batsmanWeight: number;
  wicketkeeperWeight: number;
  allRounderWeight: number;
  fastBowlerWeight: number;
  spinBowlerWeight: number;
  uncappedWeight: number;
  absoluteMaxBid: number; // max crores they would pay for any single player
  conservativeThreshold?: number; // PBKS style: only bid up to x% of base price
  
  // Custom structured target rules for each team
  targetRoleCounts: {
    batsman: number;
    wicketkeeper: number;
    allrounder: number;
    bowler: number;
    uncapped: number;
  };
  maxForeignPlayers: number; // Strictly 8
  idealBudgetDistribution: {
    batsman: number; // in Crores, total 100
    wicketkeeper: number;
    allrounder: number;
    bowler: number;
    uncapped: number;
  };
}

export interface Team {
  id: string;
  name: string;
  shortName: string;
  logo: string; // Tailwind gradient or icon specifier
  color: string; // Primary hex or tailwind class
  borderColor: string;
  isHuman: boolean;
  budget: number; // Starts at 100 Crores
  squad: PlayerBidInfo[];
  strategy: AIStrategy;
}

export interface BiddingLog {
  id: string;
  teamId: string;
  teamName: string;
  amount: number; // in Crores
  timestamp: string;
}

export type AuctionSetType = string;
