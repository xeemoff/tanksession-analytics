import { createRoot } from 'react-dom/client';
import App from './App';
import { getMode } from './contracts';
import './styles.css';

// Only native compositing should expose the hangar behind our panel.
if (getMode(window.location.search) === 'gameface') {
  document.body.className += ' native-gameface';
}
const root = document.getElementById('root');
if (root) createRoot(root).render(<App />);
