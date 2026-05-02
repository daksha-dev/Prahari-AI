import { type ClassValue, clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function getSeverityColor(score: number) {
  if (score >= 70) return 'severity-healthy';
  if (score >= 50) return 'severity-watch';
  if (score >= 30) return 'severity-risk';
  return 'severity-critical';
}

export function getSeverityHex(score: number) {
  if (score >= 70) return '#4ade80';
  if (score >= 50) return '#facc15';
  if (score >= 30) return '#fb923c';
  return '#ef4444';
}
