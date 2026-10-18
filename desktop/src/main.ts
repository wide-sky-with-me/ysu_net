import { mount } from 'svelte';
import './font.css';
import './app.css';
import './accents.css';
import App from './App.svelte';

mount(App, { target: document.getElementById('app')! });
