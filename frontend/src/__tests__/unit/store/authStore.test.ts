import { describe, it, expect, beforeEach } from 'vitest';
import { useAuthStore } from '../../../store/authStore';
import type { User } from '../../../types';

const mockUser: User = {
  id: 'user-1',
  email: 'test@example.com',
  role: 'rep',
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
  last_login_at: null,
};

describe('authStore', () => {
  beforeEach(() => {
    useAuthStore.setState({ user: null, accessToken: null, refreshToken: null });
    localStorage.clear();
  });

  it('initialises with no user or tokens', () => {
    const { user, accessToken, refreshToken } = useAuthStore.getState();
    expect(user).toBeNull();
    expect(accessToken).toBeNull();
    expect(refreshToken).toBeNull();
  });

  it('setAuth stores user and persists tokens to localStorage', () => {
    useAuthStore.getState().setAuth(mockUser, 'access-abc', 'refresh-xyz');
    const state = useAuthStore.getState();
    expect(state.user).toEqual(mockUser);
    expect(state.accessToken).toBe('access-abc');
    expect(state.refreshToken).toBe('refresh-xyz');
    expect(localStorage.getItem('access_token')).toBe('access-abc');
    expect(localStorage.getItem('refresh_token')).toBe('refresh-xyz');
  });

  it('logout clears user, tokens, and localStorage', () => {
    useAuthStore.getState().setAuth(mockUser, 'access-abc', 'refresh-xyz');
    useAuthStore.getState().logout();
    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.accessToken).toBeNull();
    expect(state.refreshToken).toBeNull();
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(localStorage.getItem('refresh_token')).toBeNull();
  });

  it('updateUser changes user data without touching tokens', () => {
    useAuthStore.getState().setAuth(mockUser, 'access-abc', 'refresh-xyz');
    useAuthStore.getState().updateUser({ ...mockUser, email: 'updated@example.com' });
    expect(useAuthStore.getState().user?.email).toBe('updated@example.com');
    expect(useAuthStore.getState().accessToken).toBe('access-abc');
  });

  describe('isAdmin', () => {
    it('returns true for admin role', () => {
      useAuthStore.getState().setAuth({ ...mockUser, role: 'admin' }, 'a', 'r');
      expect(useAuthStore.getState().isAdmin()).toBe(true);
    });

    it('returns false for manager role', () => {
      useAuthStore.getState().setAuth({ ...mockUser, role: 'manager' }, 'a', 'r');
      expect(useAuthStore.getState().isAdmin()).toBe(false);
    });

    it('returns false for rep role', () => {
      useAuthStore.getState().setAuth(mockUser, 'a', 'r');
      expect(useAuthStore.getState().isAdmin()).toBe(false);
    });

    it('returns false when no user', () => {
      expect(useAuthStore.getState().isAdmin()).toBe(false);
    });
  });

  describe('isManager', () => {
    it('returns true for manager role', () => {
      useAuthStore.getState().setAuth({ ...mockUser, role: 'manager' }, 'a', 'r');
      expect(useAuthStore.getState().isManager()).toBe(true);
    });

    it('returns true for admin role (admin is a superset of manager)', () => {
      useAuthStore.getState().setAuth({ ...mockUser, role: 'admin' }, 'a', 'r');
      expect(useAuthStore.getState().isManager()).toBe(true);
    });

    it('returns false for rep role', () => {
      useAuthStore.getState().setAuth(mockUser, 'a', 'r');
      expect(useAuthStore.getState().isManager()).toBe(false);
    });

    it('returns false when no user', () => {
      expect(useAuthStore.getState().isManager()).toBe(false);
    });
  });
});
