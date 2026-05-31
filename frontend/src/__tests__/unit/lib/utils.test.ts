import { describe, it, expect } from 'vitest';
import {
  formatDate,
  formatDateShort,
  formatPercent,
  formatScore,
  scoreColor,
  scoreLabel,
  truncate,
  cn,
} from '../../../lib/utils';

describe('formatDate', () => {
  it('formats a valid ISO date string', () => {
    const result = formatDate('2024-01-15T12:00:00Z');
    expect(result).toMatch(/Jan 15, 2024/);
  });

  it('returns em-dash for null', () => {
    expect(formatDate(null)).toBe('—');
  });

  it('returns em-dash for undefined', () => {
    expect(formatDate(undefined)).toBe('—');
  });
});

describe('formatDateShort', () => {
  it('formats without time component', () => {
    const result = formatDateShort('2024-01-15T12:00:00Z');
    expect(result).toMatch(/Jan 15, 2024/);
    expect(result).not.toMatch(/:/);
  });

  it('returns em-dash for null', () => {
    expect(formatDateShort(null)).toBe('—');
  });
});

describe('formatPercent', () => {
  it('formats 0.5 as 50%', () => {
    expect(formatPercent(0.5)).toBe('50%');
  });

  it('formats 1 as 100%', () => {
    expect(formatPercent(1)).toBe('100%');
  });

  it('rounds fractional percentages', () => {
    expect(formatPercent(0.178)).toBe('18%');
  });

  it('returns em-dash for null', () => {
    expect(formatPercent(null)).toBe('—');
  });

  it('returns em-dash for undefined', () => {
    expect(formatPercent(undefined)).toBe('—');
  });
});

describe('formatScore', () => {
  it('converts 0-1 float to 0-100 integer string', () => {
    expect(formatScore(0.95)).toBe('95');
  });

  it('returns em-dash for null', () => {
    expect(formatScore(null)).toBe('—');
  });
});

describe('scoreColor', () => {
  it('returns emerald for score >= 0.8', () => {
    expect(scoreColor(0.9)).toContain('emerald');
  });

  it('returns yellow for score >= 0.6 and < 0.8', () => {
    expect(scoreColor(0.7)).toContain('yellow');
  });

  it('returns orange for score >= 0.4 and < 0.6', () => {
    expect(scoreColor(0.5)).toContain('orange');
  });

  it('returns red for score < 0.4', () => {
    expect(scoreColor(0.2)).toContain('red');
  });

  it('returns muted for null', () => {
    expect(scoreColor(null)).toContain('muted');
  });
});

describe('scoreLabel', () => {
  it('returns Excellent for >= 0.8', () => {
    expect(scoreLabel(0.85)).toBe('Excellent');
  });

  it('returns Good for >= 0.6', () => {
    expect(scoreLabel(0.65)).toBe('Good');
  });

  it('returns Fair for >= 0.4', () => {
    expect(scoreLabel(0.45)).toBe('Fair');
  });

  it('returns Poor for < 0.4', () => {
    expect(scoreLabel(0.3)).toBe('Poor');
  });

  it('returns Unscored for null', () => {
    expect(scoreLabel(null)).toBe('Unscored');
  });
});

describe('truncate', () => {
  it('leaves short strings unchanged', () => {
    expect(truncate('hello', 10)).toBe('hello');
  });

  it('truncates long strings with ellipsis', () => {
    const result = truncate('hello world!', 8);
    expect(result).toBe('hello w…');
    expect(result.length).toBe(8);
  });

  it('handles string exactly at limit', () => {
    expect(truncate('12345', 5)).toBe('12345');
  });
});

describe('cn', () => {
  it('merges class names', () => {
    expect(cn('foo', 'bar')).toBe('foo bar');
  });

  it('resolves tailwind conflicts (last wins)', () => {
    expect(cn('text-red-500', 'text-blue-500')).toBe('text-blue-500');
  });

  it('handles conditional classes', () => {
    const condition = false;
    expect(cn('base', condition && 'hidden', 'active')).toBe('base active');
  });
});
