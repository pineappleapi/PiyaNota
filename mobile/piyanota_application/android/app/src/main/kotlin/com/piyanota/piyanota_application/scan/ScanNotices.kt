package com.piyanota.piyanota_application.scan

/**
 * The plain logic behind the conversion notifications (PIYA-218, user
 * decision 2026-10-22), free of Android types so the JVM tests can check
 * it. [ScanNotifications] and [ScanTrackingService] use it.
 */
internal object ScanNotices {
    /** The extra on a result notification's tap: which job to open. */
    const val EXTRA_JOB_ID = "com.piyanota.piyanota_application.scan.JOB_ID"

    /**
     * One result notification per job, so two scans that finish while the
     * app is away both stay in the shade. Posted under [ScanNotifications]'
     * own tag, so these ids never clash with the export's.
     */
    fun resultId(jobId: String): Int = jobId.hashCode() and Int.MAX_VALUE

    /**
     * dataSync on Android 10+: the service only keeps the app's polling of
     * the server alive (it is a sync of the job's state), and no other
     * type fits. mediaProcessing is for on-device media work, which this
     * is not, and shortService's 3 min limit is too tight for a scan that
     * pauses for a lost connection. Older Android has no types. On 15+
     * dataSync has a 6 h daily limit; [ScanTrackingService.onTimeout]
     * leaves the foreground if it is ever reached.
     * Value is android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC.
     */
    fun serviceType(sdkInt: Int): Int? = if (sdkInt >= TYPED_SERVICES_SDK) TYPE_DATA_SYNC else null

    const val TYPE_DATA_SYNC = 0x00000001
    private const val TYPED_SERVICES_SDK = 29
}
