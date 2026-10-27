const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('kairosDesktop', {
  isElectron: true,
  version: '2.0.0',
  getGithubAuthInfo: () => ipcRenderer.invoke('kairos:github-auth-info'),
  triggerGithubSignIn: (returnUrl) => ipcRenderer.invoke('kairos:github-signin', returnUrl),
});
