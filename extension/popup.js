'use strict';

document.addEventListener('DOMContentLoaded', function () {
  var btn = document.getElementById('open-qgrab');
  if (!btn) return;
  btn.addEventListener('click', function () {
    var url = 'https://qgrab.onrender.com/';
    if (typeof chrome !== 'undefined' && chrome.tabs && chrome.tabs.create) {
      chrome.tabs.create({ url: url });
    } else {
      window.open(url, '_blank', 'noopener');
    }
  });
});
