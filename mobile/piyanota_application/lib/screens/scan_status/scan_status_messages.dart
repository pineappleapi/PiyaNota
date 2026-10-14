/// PIYA-218 copy, quoted from the scan-status spec's §9 copy table where
/// it has a row (AC12). Tests assert on these, so change them deliberately.
class ScanStatusMessages {
  ScanStatusMessages._();

  // Library card (AC4, spec §4/§9 "Converting… 60%").
  static String converting(int percent) => 'Converting… $percent%';
  static const String stalled = 'Still working, this one\'s a long piece.';
  static const String paused = 'Scan paused — no connection';
  static const String retry = 'Try again';
  static const String failedCard = 'This scan didn\'t work. Tap to see why.';
  static String cardSemantics(String title, int percent) =>
      '$title, scan in progress, $percent percent';
  static String pausedSemantics(String title) => '$title, scan paused';
  static const String longPressHint = 'cancel scan';

  // Bell (AC5).
  static const String bellIdle = 'Notifications';
  static String bellSemantics({required int unread, required bool active}) {
    final parts = <String>['Notifications'];
    if (unread > 0) parts.add('$unread unread');
    if (active) parts.add('a scan is in progress');
    return parts.join(', ');
  }

  /// The badge stops counting here so it fits the dot.
  static const int maxBadgeCount = 9;
  static String badge(int count) =>
      count > maxBadgeCount ? '$maxBadgeCount+' : '$count';

  // Panel (AC6, spec §5.3/§9).
  static const String panelTitle = 'Notifications';
  static const String panelSubtitle = 'Your recent scans';
  static const String markAllRead = 'Mark all as read';
  static const String empty = 'No notifications yet.';
  static const String processingRow =
      ' is still being converted. Hang on '
      'tight!';
  static const String readyRow = ' is ready to play';
  static const String failedRow = ' couldn\'t be converted';
  static const String failedRowHint = 'Tap to see what happened';
  static const String pausedRowHint = 'Paused — no connection';
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
  static String failedToast(String title) => '$title couldn\'t be converted.';
  static const String open = 'Open';
  static const String view = 'View';
  static const String dismissToast = 'Dismiss';

  // Failure view Delete (AC3).
  static const String deleteScan = 'Delete';
}
