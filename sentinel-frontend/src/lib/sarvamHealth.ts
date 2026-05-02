export type SarvamHealth = 'on' | 'degraded' | 'offline';

interface State {
  health: SarvamHealth;
  failures: number;
}

let state: State = { health: 'on', failures: 0 };
const listeners = new Set<(state: State) => void>();

const emit = () => {
  listeners.forEach(listener => listener(state));
};

export function reportSarvamSuccess() {
  state = { health: 'on', failures: 0 };
  emit();
}

export function reportSarvamFailure() {
  const failures = state.failures + 1;
  state = { failures, health: failures >= 3 ? 'offline' : 'degraded' };
  emit();
}

export function getSarvamHealth() {
  return state;
}

export function subscribeSarvamHealth(listener: (state: State) => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
