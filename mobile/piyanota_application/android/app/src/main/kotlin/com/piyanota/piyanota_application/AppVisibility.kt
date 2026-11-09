package com.piyanota.piyanota_application

/**
 * Whether the user is in this app: an Activity of it is on screen
 * (between onResume and onPause, set by [MainActivity]), or the export's
 * own folder picker is open over it (set by ExportChannel), which pauses
 * the Activity without the user having left. Read by the export worker to
 * avoid a system notification that repeats the in-app banner. All on the
 * main thread.
 */
internal object AppVisibility {
    @Volatile
    var resumed = false

    @Volatile
    var ownPickerOpen = false

    val visible: Boolean get() = resumed || ownPickerOpen
}
