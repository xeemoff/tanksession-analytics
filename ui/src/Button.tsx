import type { ButtonHTMLAttributes } from 'react';

// The client Gameface build does not support the :disabled selector.
// Keep native disabled behaviour and expose the same state to compatible CSS.
export function Button({ className = '', disabled = false, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...props} disabled={disabled} className={(className + (disabled ? ' is-disabled' : ' is-enabled')).trim()} />;
}
