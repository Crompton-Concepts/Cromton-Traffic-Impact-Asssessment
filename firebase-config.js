// ============================================================
//  Firebase Configuration — TIA Crompton Concepts
//  ============================================================
//  NOTE: No import/require needed — Firebase is loaded via CDN
//  script tags in each HTML file. This file just declares the
//  config object that user-sync.js picks up automatically.
//
//  SECURITY NOTE: This file is public on GitHub Pages — that is fine.
//  The API key only identifies the project. Access is controlled by
//  Firebase Security Rules, not the key itself.
// ============================================================

const FIREBASE_CONFIG = {
  apiKey:            "AIzaSyA8_CBlh3dCbjxn6A3jO_6MxgRr78o4oWo",
  authDomain:        "crompton-apps.firebaseapp.com",
  // NOTE: Enable Realtime Database in the Firebase console, then verify this URL.
  // Default RTDB URL format: https://<project-id>-default-rtdb.firebaseio.com
  databaseURL:       "https://crompton-apps-default-rtdb.firebaseio.com",
  projectId:         "crompton-apps",
  storageBucket:     "crompton-apps.firebasestorage.app",
  messagingSenderId: "896651039604",
  appId:             "1:896651039604:web:87d8321762c1b7acd11221",
  measurementId:     "G-DGNYLXYL3L"
};