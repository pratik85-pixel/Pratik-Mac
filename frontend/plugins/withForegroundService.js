/**
 * Expo config plugin for @supersami/rn-foreground-service
 *
 * Adds to AndroidManifest.xml:
 *  - FOREGROUND_SERVICE permission
 *  - FOREGROUND_SERVICE_CONNECTED_DEVICE permission (Android 14+, needed for BLE)
 *  - WAKE_LOCK permission
 *  - ForegroundService + ForegroundServiceTask service declarations
 *
 * Also copies assets/notification-icon.png to res/drawable-DENSITY/ic_notification.png
 * so @supersami/rn-foreground-service can resolve it via getIdentifier("ic_notification","drawable",...).
 * (ic_launcher lives in mipmap/, not drawable/, which getIdentifier doesn't search under "drawable".)
 */
const path = require('path');
const fs = require('fs');
const { withAndroidManifest, withDangerousMod } = require('@expo/config-plugins');

/** Adds an element to the parent only if it is not already present (idempotent). */
function addIfMissing(parent, tag, attrs) {
  const existing = (parent[tag] || []).find((el) =>
    Object.entries(attrs).every(([k, v]) => el.$[k] === v),
  );
  if (!existing) {
    parent[tag] = [...(parent[tag] || []), { $: attrs }];
  }
}

/**
 * Copy assets/notification-icon.png  android/app/src/main/res/drawable[-*]/ic_notification.png
 * for every density bucket that already exists, plus the base drawable/ folder.
 * This runs during the prebuild/generate phase (withDangerousMod).
 */
function withNotificationIcon(config) {
  return withDangerousMod(config, [
    'android',
    (mod) => {
      const srcIcon = path.resolve(mod.modRequest.projectRoot, 'assets', 'notification-icon.png');
      if (!fs.existsSync(srcIcon)) {
        console.warn('[withForegroundService] WARNING: assets/notification-icon.png not found  ic_notification will be missing!');
        return mod;
      }
      const resDir = path.join(mod.modRequest.platformProjectRoot, 'app', 'src', 'main', 'res');
      // Copy into base drawable/ and every existing drawable-<density>/ folder
      const targets = fs.readdirSync(resDir).filter((d) => d === 'drawable' || d.startsWith('drawable-'));
      // Always ensure base drawable/ exists
      if (!targets.includes('drawable')) {
        fs.mkdirSync(path.join(resDir, 'drawable'), { recursive: true });
        targets.push('drawable');
      }
      for (const dir of targets) {
        const dest = path.join(resDir, dir, 'ic_notification.png');
        fs.copyFileSync(srcIcon, dest);
      }
      console.log(`[withForegroundService] Copied ic_notification.png to ${targets.length} drawable dir(s)`);
      return mod;
    },
  ]);
}

module.exports = function withForegroundService(config) {
  // 1. Copy the notification icon into drawable folders
  config = withNotificationIcon(config);

  // 2. Patch AndroidManifest.xml
  return withAndroidManifest(config, (mod) => {
    const manifest = mod.modResults.manifest;

    //  Permissions 
    addIfMissing(manifest, 'uses-permission', {
      'android:name': 'android.permission.FOREGROUND_SERVICE',
    });
    addIfMissing(manifest, 'uses-permission', {
      'android:name': 'android.permission.FOREGROUND_SERVICE_CONNECTED_DEVICE',
    });
    addIfMissing(manifest, 'uses-permission', {
      'android:name': 'android.permission.WAKE_LOCK',
    });

    //  Service declarations 
    const app = manifest.application[0];

    const services = app.service || [];

    function servicePresent(name) {
      return services.some((s) => s.$['android:name'] === name);
    }

    if (!servicePresent('com.supersami.foregroundservice.ForegroundService')) {
      services.push({
        $: {
          'android:name': 'com.supersami.foregroundservice.ForegroundService',
          'android:foregroundServiceType': 'connectedDevice',
        },
      });
    }

    if (!servicePresent('com.supersami.foregroundservice.ForegroundServiceTask')) {
      services.push({
        $: {
          'android:name':
            'com.supersami.foregroundservice.ForegroundServiceTask',
          'android:foregroundServiceType': 'connectedDevice',
        },
      });
    }

    app.service = services;
    return mod;
  });
};
