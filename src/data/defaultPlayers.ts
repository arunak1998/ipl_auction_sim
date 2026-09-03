import { Player } from '../types';

export const DEFAULT_PLAYERS: Player[] = [
  // --- Marquee Players (Highly rated, high base price) ---
  {
    id: 'm1',
    name: 'Virat Kohli',
    basePrice: 2.0,
    role: 'Batsman',
    status: 'Capped',
    rating: 98,
    isMarquee: true,
    country: 'India'
  },
  {
    id: 'm2',
    name: 'Jasprit Bumrah',
    basePrice: 2.0,
    role: 'Fast Bowler',
    status: 'Capped',
    rating: 99,
    isMarquee: true,
    country: 'India'
  },
  {
    id: 'm3',
    name: 'Rishabh Pant',
    basePrice: 2.0,
    role: 'Wicketkeeper',
    status: 'Capped',
    rating: 95,
    isMarquee: true,
    country: 'India'
  },
  {
    id: 'm4',
    name: 'Rashid Khan',
    basePrice: 2.0,
    role: 'Spin Bowler',
    status: 'Capped',
    rating: 97,
    isMarquee: true,
    country: 'Afghanistan'
  },
  {
    id: 'm5',
    name: 'Heinrich Klaasen',
    basePrice: 2.0,
    role: 'Wicketkeeper',
    status: 'Capped',
    rating: 96,
    isMarquee: true,
    country: 'South Africa'
  },
  {
    id: 'm6',
    name: 'Hardik Pandya',
    basePrice: 2.0,
    role: 'All-Rounder',
    status: 'Capped',
    rating: 94,
    isMarquee: true,
    country: 'India'
  },
  {
    id: 'm7',
    name: 'Travis Head',
    basePrice: 2.0,
    role: 'Batsman',
    status: 'Capped',
    rating: 95,
    isMarquee: true,
    country: 'Australia'
  },
  {
    id: 'm8',
    name: 'Sunil Narine',
    basePrice: 2.0,
    role: 'All-Rounder',
    status: 'Capped',
    rating: 96,
    isMarquee: true,
    country: 'West Indies'
  },
  {
    id: 'm9',
    name: 'Pat Cummins',
    basePrice: 2.0,
    role: 'Fast Bowler',
    status: 'Capped',
    rating: 96,
    isMarquee: true,
    country: 'Australia'
  },
  {
    id: 'm10',
    name: 'Yuzvendra Chahal',
    basePrice: 2.0,
    role: 'Spin Bowler',
    status: 'Capped',
    rating: 92,
    isMarquee: true,
    country: 'India'
  },

  // --- Batsmen ---
  {
    id: 'b1',
    name: 'Rohit Sharma',
    basePrice: 2.0,
    role: 'Batsman',
    status: 'Capped',
    rating: 94,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'b2',
    name: 'Yashasvi Jaiswal',
    basePrice: 2.0,
    role: 'Batsman',
    status: 'Capped',
    rating: 93,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'b3',
    name: 'Shubman Gill',
    basePrice: 2.0,
    role: 'Batsman',
    status: 'Capped',
    rating: 92,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'b4',
    name: 'Suryakumar Yadav',
    basePrice: 2.0,
    role: 'Batsman',
    status: 'Capped',
    rating: 96,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'b5',
    name: 'Rinku Singh',
    basePrice: 1.5,
    role: 'Batsman',
    status: 'Capped',
    rating: 89,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'b6',
    name: 'Ruturaj Gaikwad',
    basePrice: 1.5,
    role: 'Batsman',
    status: 'Capped',
    rating: 90,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'b7',
    name: 'Sai Sudharsan',
    basePrice: 1.0,
    role: 'Batsman',
    status: 'Capped',
    rating: 86,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'b8',
    name: 'Tristan Stubbs',
    basePrice: 1.5,
    role: 'Batsman',
    status: 'Capped',
    rating: 91,
    isMarquee: false,
    country: 'South Africa'
  },

  // --- Wicketkeepers ---
  {
    id: 'wk1',
    name: 'Sanju Samson',
    basePrice: 2.0,
    role: 'Wicketkeeper',
    status: 'Capped',
    rating: 92,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'wk2',
    name: 'Nicholas Pooran',
    basePrice: 2.0,
    role: 'Wicketkeeper',
    status: 'Capped',
    rating: 94,
    isMarquee: false,
    country: 'West Indies'
  },
  {
    id: 'wk3',
    name: 'KL Rahul',
    basePrice: 2.0,
    role: 'Wicketkeeper',
    status: 'Capped',
    rating: 91,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'wk4',
    name: 'Phil Salt',
    basePrice: 1.5,
    role: 'Wicketkeeper',
    status: 'Capped',
    rating: 89,
    isMarquee: false,
    country: 'England'
  },
  {
    id: 'wk5',
    name: 'Ishan Kishan',
    basePrice: 1.5,
    role: 'Wicketkeeper',
    status: 'Capped',
    rating: 88,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'wk6',
    name: 'Jitesh Sharma',
    basePrice: 1.0,
    role: 'Wicketkeeper',
    status: 'Capped',
    rating: 83,
    isMarquee: false,
    country: 'India'
  },

  // --- All-Rounders ---
  {
    id: 'ar1',
    name: 'Ravindra Jadeja',
    basePrice: 2.0,
    role: 'All-Rounder',
    status: 'Capped',
    rating: 95,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'ar2',
    name: 'Axar Patel',
    basePrice: 2.0,
    role: 'All-Rounder',
    status: 'Capped',
    rating: 93,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'ar3',
    name: 'Marcus Stoinis',
    basePrice: 1.5,
    role: 'All-Rounder',
    status: 'Capped',
    rating: 88,
    isMarquee: false,
    country: 'Australia'
  },
  {
    id: 'ar4',
    name: 'Glenn Maxwell',
    basePrice: 2.0,
    role: 'All-Rounder',
    status: 'Capped',
    rating: 91,
    isMarquee: false,
    country: 'Australia'
  },
  {
    id: 'ar5',
    name: 'Liam Livingstone',
    basePrice: 1.5,
    role: 'All-Rounder',
    status: 'Capped',
    rating: 87,
    isMarquee: false,
    country: 'England'
  },
  {
    id: 'ar6',
    name: 'Sam Curran',
    basePrice: 2.0,
    role: 'All-Rounder',
    status: 'Capped',
    rating: 89,
    isMarquee: false,
    country: 'England'
  },
  {
    id: 'ar7',
    name: 'Andre Russell',
    basePrice: 2.0,
    role: 'All-Rounder',
    status: 'Capped',
    rating: 93,
    isMarquee: false,
    country: 'West Indies'
  },
  {
    id: 'ar8',
    name: 'Nitish Kumar Reddy',
    basePrice: 1.0,
    role: 'All-Rounder',
    status: 'Capped',
    rating: 85,
    isMarquee: false,
    country: 'India'
  },

  // --- Fast Bowlers ---
  {
    id: 'fb1',
    name: 'Mitchell Starc',
    basePrice: 2.0,
    role: 'Fast Bowler',
    status: 'Capped',
    rating: 93,
    isMarquee: false,
    country: 'Australia'
  },
  {
    id: 'fb2',
    name: 'Matheesha Pathirana',
    basePrice: 1.5,
    role: 'Fast Bowler',
    status: 'Capped',
    rating: 91,
    isMarquee: false,
    country: 'Sri Lanka'
  },
  {
    id: 'fb3',
    name: 'Mohammed Siraj',
    basePrice: 2.0,
    role: 'Fast Bowler',
    status: 'Capped',
    rating: 90,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'fb4',
    name: 'Arshdeep Singh',
    basePrice: 2.0,
    role: 'Fast Bowler',
    status: 'Capped',
    rating: 92,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'fb5',
    name: 'Trent Boult',
    basePrice: 2.0,
    role: 'Fast Bowler',
    status: 'Capped',
    rating: 91,
    isMarquee: false,
    country: 'New Zealand'
  },
  {
    id: 'fb6',
    name: 'Kagiso Rabada',
    basePrice: 2.0,
    role: 'Fast Bowler',
    status: 'Capped',
    rating: 92,
    isMarquee: false,
    country: 'South Africa'
  },
  {
    id: 'fb7',
    name: 'Harshal Patel',
    basePrice: 1.5,
    role: 'Fast Bowler',
    status: 'Capped',
    rating: 87,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'fb8',
    name: 'Mayank Yadav',
    basePrice: 1.0,
    role: 'Fast Bowler',
    status: 'Capped',
    rating: 88,
    isMarquee: false,
    country: 'India'
  },

  // --- Spin Bowlers ---
  {
    id: 'sb1',
    name: 'Kuldeep Yadav',
    basePrice: 2.0,
    role: 'Spin Bowler',
    status: 'Capped',
    rating: 94,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'sb2',
    name: 'Ravi Bishnoi',
    basePrice: 1.5,
    role: 'Spin Bowler',
    status: 'Capped',
    rating: 89,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'sb3',
    name: 'Varun Chakaravarthy',
    basePrice: 1.5,
    role: 'Spin Bowler',
    status: 'Capped',
    rating: 91,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'sb4',
    name: 'Adam Zampa',
    basePrice: 2.0,
    role: 'Spin Bowler',
    status: 'Capped',
    rating: 90,
    isMarquee: false,
    country: 'Australia'
  },
  {
    id: 'sb5',
    name: 'Wanindu Hasaranga',
    basePrice: 1.5,
    role: 'Spin Bowler',
    status: 'Capped',
    rating: 89,
    isMarquee: false,
    country: 'Sri Lanka'
  },
  {
    id: 'sb6',
    name: 'Rahul Chahar',
    basePrice: 0.75,
    role: 'Spin Bowler',
    status: 'Capped',
    rating: 82,
    isMarquee: false,
    country: 'India'
  },

  // --- Uncapped Players (Typically cheap base price, 0.20-0.50 Crores) ---
  {
    id: 'uc1',
    name: 'Abhishek Sharma',
    basePrice: 0.50,
    role: 'All-Rounder',
    status: 'Uncapped',
    rating: 89,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc2',
    name: 'Ayush Badoni',
    basePrice: 0.30,
    role: 'Batsman',
    status: 'Uncapped',
    rating: 82,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc3',
    name: 'Ashutosh Sharma',
    basePrice: 0.20,
    role: 'Batsman',
    status: 'Uncapped',
    rating: 83,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc4',
    name: 'Shashank Singh',
    basePrice: 0.30,
    role: 'All-Rounder',
    status: 'Uncapped',
    rating: 84,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc5',
    name: 'Ramandeep Singh',
    basePrice: 0.20,
    role: 'All-Rounder',
    status: 'Uncapped',
    rating: 81,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc6',
    name: 'Suyash Sharma',
    basePrice: 0.20,
    role: 'Spin Bowler',
    status: 'Uncapped',
    rating: 80,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc7',
    name: 'Nehal Wadhera',
    basePrice: 0.30,
    role: 'Batsman',
    status: 'Uncapped',
    rating: 82,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc8',
    name: 'Yash Dayal',
    basePrice: 0.50,
    role: 'Fast Bowler',
    status: 'Uncapped',
    rating: 83,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc9',
    name: 'Rasikh Salam',
    basePrice: 0.20,
    role: 'Fast Bowler',
    status: 'Uncapped',
    rating: 80,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc10',
    name: 'Anukul Roy',
    basePrice: 0.20,
    role: 'Spin Bowler',
    status: 'Uncapped',
    rating: 79,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc11',
    name: 'Angkrish Raghuvanshi',
    basePrice: 0.20,
    role: 'Batsman',
    status: 'Uncapped',
    rating: 81,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc12',
    name: 'Vaibhav Arora',
    basePrice: 0.30,
    role: 'Fast Bowler',
    status: 'Uncapped',
    rating: 82,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc13',
    name: 'Sameer Rizvi',
    basePrice: 0.30,
    role: 'Batsman',
    status: 'Uncapped',
    rating: 79,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc14',
    name: 'Kumar Kushagra',
    basePrice: 0.20,
    role: 'Wicketkeeper',
    status: 'Uncapped',
    rating: 78,
    isMarquee: false,
    country: 'India'
  },
  {
    id: 'uc15',
    name: 'Musheer Khan',
    basePrice: 0.20,
    role: 'All-Rounder',
    status: 'Uncapped',
    rating: 84,
    isMarquee: false,
    country: 'India'
  }
];
