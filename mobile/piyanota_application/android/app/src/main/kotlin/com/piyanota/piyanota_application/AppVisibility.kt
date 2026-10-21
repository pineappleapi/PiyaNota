package com.piyanota.piyanota_application

/**
 * Whether an Activity of this app is on screen (between onResume and
 * onPause). Set on the main thread by [MainActivity]; read by the export
 * worker to avoid a system notification that repeats the in-app banner.
 */
internal object AppVisibility {
    @Volatile
    var visible = false
}
