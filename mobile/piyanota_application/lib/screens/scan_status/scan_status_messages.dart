/// PIYA-218 copy, quoted from the scan-status spec's §9 copy table where
/// it has a row (AC12). Tests assert on these, so change them deliberately.
class ScanStatusMessages {
  ScanStatusMessages._();

  // Library card (AC4, spec §4/§9 "Converting… 60%").
  static String converting(int percent) => 'Converting… $percent%';
  static const String stalled = 'Still working, this one\'s a long piece.';
  // Neutral: a pause follows 30 s of failed polls, whether the phone is
  // offline or the server is answering 5xx (same tone as Processing's
  // "We can't reach PiyaNota right now").
  static const String paused = 'Scan paused — can\'t reach PiyaNota';
  static const String retry = 'Try again';
  static const String failedCard = 'This scan didn\'t work. Tap to see why.';
  static String cardSemantics(String title, int percent) =>
      '$title, scan in progress, $percent percent';
  static String pausedSemantics(String title) => '$title, scan paused';
  static const String longPressHint = 'cancel scan';

  // Bell (AC5).
  static const String bellIdle = 'Notifications';
  static String bellSemantics({
    required int unread,
    required bool active,
    bool exporting = false,
  }) {
    final parts = <String>['Notifications'];
    if (unread > 0) parts.add('$unread unread');
    if (active) parts.add('a scan is in progress');
    if (exporting) parts.add('an export is in progress');
    return parts.join(', ');
  }

  /// The badge stops counting here so it fits the dot.
  static const int maxBadgeCount = 9;
  static String badge(int count) =>
      count > maxBadgeCount ? '$maxBadgeCount+' : '$count';

  // Panel (AC6, spec §5.3/§9).
  static const String panelTitle = 'Notifications';
  static const String panelSubtitle = 'Your recent scans and exports';
  static const String markAllRead = 'Mark all as read';
  static const String empty = 'No notifications yet.';
  static const String processingRow =
      ' is still being converted. Hang on '
      'tight!';
  static const String readyRow = ' is ready to play';
  static const String failedRow = ' couldn\'t be converted';
  static const String failedRowHint = 'Tap to see what happened';
  static const String pausedRowHint =
      'Paused — we can\'t reach PiyaNota right now';
  static const String dismissHint = 'Swipe to dismiss';
  static const String unread = 'unread';

  /// "Just now", "5 min ago", "2 h ago", "3 days ago".
  static String relativeTime(Duration age) {
    if (age.inMinutes < 1) return 'Just now';
    if (age.inHours < 1) return '${age.inMinutes} min ago';
    if (age.inDays < 1) return '${age.inHours} h ago';
    return age.inDays == 1 ? 'Yesterday' : '${age.inDays} days ago';
  }

  // Toast (AC7, spec §6/§9 "[Score] is ready. [Open]").
  static String readyToast(String title) => '$title is ready.';
  static String failedToast(String title) => '$title\'s scan didn\'t work.';
  static const String open = 'Open';
  static const String view = 'View';
  static const String dismissToast = 'Dismiss';

  // System notifications while the app is away (user decision
  // 2026-10-22): the ongoing one, then one per finished scan. AC12: "scan"
  // and "piano guide", no "convert".
  static String scanningInBackground(List<String> titles) => titles.length == 1
      ? 'Scanning ${titles.single}…'
      : 'Scanning ${titles.length} scores…';

  /// Every scan still followed is paused for want of a network (AC10); it
  /// carries on by itself once the connection returns.
  static const String waitingForConnection = 'Waiting for connection…';

  /// AC7's background wording, word for word.
  static String readyNotification(String title) =>
      'Your piano guide for $title is ready.';
  static const String readyNotificationHint = 'Tap to play it.';

  // Asked once on Android 13+ when a scan is first sent to the background
  // (Convert in Background, the back arrow or system back), unless the
  // first export already asked. AC11: a one-line reason. The buttons match
  // the export's prompt (ExportMessages).
  static const String notificationsTitle = 'Tell you when it\'s ready?';
  static const String notificationsBody =
      'We\'ll let you know when your piano guide is ready.';
  static const String notificationsLater = 'Not now';
  static const String notificationsAllow = 'Allow';

  // Failure view Delete (AC3).
  static const String deleteScan = 'Delete';
}
