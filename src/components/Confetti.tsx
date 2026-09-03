import { useState, useEffect } from 'react';

export default function Confetti() {
  const [pieces, setPieces] = useState<{ id: number; x: number; y: number; color: string; size: number; delay: number }[]>([]);

  useEffect(() => {
    const colors = ['#f59e0b', '#10b981', '#3b82f6', '#ec4899', '#8b5cf6', '#ef4444'];
    const newPieces = Array.from({ length: 60 }).map((_, i) => ({
      id: i,
      x: Math.random() * 100, // random percentage horizontal
      y: -10 - Math.random() * 20, // start above viewport
      color: colors[Math.floor(Math.random() * colors.length)],
      size: 6 + Math.random() * 10, // size in pixels
      delay: Math.random() * 2, // delay in seconds
    }));
    setPieces(newPieces);

    // Clean up after animation finishes (approx 5 seconds)
    const timer = setTimeout(() => {
      setPieces([]);
    }, 5000);

    return () => clearTimeout(timer);
  }, []);

  if (pieces.length === 0) return null;

  return (
    <div className="fixed inset-0 pointer-events-none z-50 overflow-hidden" id="confetti-container">
      {pieces.map((piece) => (
        <div
          key={piece.id}
          className="absolute rounded-sm animate-fall"
          style={{
            left: `${piece.x}%`,
            top: `${piece.y}%`,
            width: `${piece.size}px`,
            height: `${piece.size * 0.7}px`,
            backgroundColor: piece.color,
            opacity: 0.8,
            animationDelay: `${piece.delay}s`,
            animationDuration: `${3 + Math.random() * 2}s`,
            transform: `rotate(${Math.random() * 360}deg)`,
          }}
        />
      ))}

      <style>{`
        @keyframes fall {
          0% {
            transform: translateY(0) rotate(0deg);
          }
          100% {
            transform: translateY(110vh) rotate(720deg);
          }
        }
        .animate-fall {
          animation: fall linear infinite;
        }
      `}</style>
    </div>
  );
}
