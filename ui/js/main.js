import { state } from './state.js';
import { copyCode, closeModal, copyModalDesc } from './utils.js';
import {
  showPage, updateWordCount, showResult, copyDesc, setProgress, appendLog, clearLog,
  animatePulse, resetGenBtn, renderVoicePool, collectVoicePool, renderReview, stat, toggleSchedLog
} from './ui.js';
import {
  runSystemCheck, installPackages, startGeneration, generateShort, pollStatus, loadOutputs,
  refreshAnalytics, deleteOutput, loadMusic, uploadMusic, deleteMusic, generateScriptWithAI,
  loadJobs, toggleJobDetail, cleanupJobs, runStorageCleanup, loadBrandingSlots, uploadBranding,
  deleteBranding, loadDashboard, loadScheduler, saveSchedulerInline, triggerScheduler, harvestIdeas,
  loadIdeas, setIdeaStatus, deleteIdea, produceIdea, reviewVideo, refreshYTStatus, ytInstall,
  ytUploadSecrets, ytAuthorize, ytRevoke, ytUploadVideo, testThumbnail, loadSettings,
  refreshCaptionInstallStatus, installCaptions, validateAndSaveOpenrouter, validateAndSavePexels,
  saveSettings
} from './api.js';

// Expose all to global scope so HTML inline onclicks work
Object.assign(window, {
  showPage, loadJobs, cleanupJobs, runSystemCheck, installPackages, copyCode,
  generateScriptWithAI, generateShort, updateWordCount, startGeneration, testThumbnail,
  copyDesc, harvestIdeas, loadIdeas, refreshAnalytics, loadOutputs, uploadMusic,
  validateAndSaveOpenrouter, validateAndSavePexels, toggleSchedLog, ytInstall,
  ytUploadSecrets, ytAuthorize, ytRevoke, installCaptions, saveSettings, closeModal,
  copyModalDesc, toggleJobDetail, deleteOutput, deleteMusic, runStorageCleanup,
  uploadBranding, deleteBranding, saveSchedulerInline, triggerScheduler, setIdeaStatus,
  deleteIdea, produceIdea, reviewVideo, ytUploadVideo
});

document.addEventListener('DOMContentLoaded', () => {
  runSystemCheck();
});

// Drag and drop for music
const dz = document.getElementById('dropzone');
if (dz) {
  dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('drag-over'); });
  dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));
  dz.addEventListener('drop', e => {
    e.preventDefault(); dz.classList.remove('drag-over');
    uploadMusic(e.dataTransfer.files);
  });
}
