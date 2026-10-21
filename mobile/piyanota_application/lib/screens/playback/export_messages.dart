import '../../models/voice_part.dart';
import '../../services/export_service.dart';

/// Every user-facing string on the Export Audio modal (PIYA-211), in
/// plain words for choir members (NFR-3). No error codes.
class ExportMessages {
  ExportMessages._();

  // Wording from references/PIYA211_ExportAudioModal_UI_1.png.
  static const String title = 'Export Audio';
  static const String allVoices = 'All Voices';
  static const String withClick = 'Include metronome/click';
  static const String download = 'Download Audio';
  static const String preparing = 'Preparing audio…';

  // Screen-reader labels for the checkboxes (AC21): the pill beside each
  // box is a separate, unlabelled widget, so the box names itself.
  static String voiceBox(VoicePart voice) => 'Export ${voice.label}';
  static const String allVoicesBox = 'Export all voices';
  static const String clickBox = 'Include the metronome click';

  /// Under a voice that failed or can't be read (Review Focus 4).
  static String voiceUnavailable(VoicePart voice) =>
      '${voice.label} can’t be played, so it can’t be exported.';

  // While the file is made, and after Cancel.
  static const String progressLabel = 'Making the audio file';

  /// The X beside the bar (user decision 2026-10-21): tooltip and spoken
  /// label.
  static const String cancelExport = 'Cancel export';
  static const String cancelling = 'Cancelling…';
  static const String cancelled = 'Export cancelled. Nothing was saved.';

  /// The save was stopped part-way and the unfinished file could not be
  /// removed (L8), so "Nothing was saved" would be untrue.
  static const String cancelledPartial =
      'Export cancelled. Part of the file may still be in the folder you '
      'picked; you can delete it there.';

  /// The same whole number the bar's screen-reader value says.
  static String percent(double fraction) => '${(fraction * 100).floor()}%';

  /// The picked folder is on Drive, another app or the cloud; exports are
  /// saved only on the phone (user decision 2026-10-21). The picker
  /// opens again straight away.
  static const String notLocalFolder = 'Pick a folder on this phone.';

  // Failures (AC18, AC20); each one says what to do next.
  static const String storageFull =
      'Not enough space on this phone. Free up some space and try again.';
  // Folder access is granted per folder through the picker; there is no
  // app permission in Settings to point the user to.
  static const String permissionDenied =
      'PiyaNota can’t save to that folder. Choose another folder and try '
      'again.';
  static const String noFolderPicker =
      'This phone has no app for choosing a folder, so the file can’t be '
      'saved.';
  static const String generationFailed =
      'The audio file couldn’t be made. Try again.';

  /// Every ticked voice failed while the folder picker was open, so there
  /// is nothing to retry: no Retry, and no "try again".
  static const String nothingToExport =
      'The voices you picked can’t be played right now, so there’s nothing '
      'to export.';
  static const String interrupted =
      'The download stopped before it finished. Try again.';
  static const String retry = 'Retry';

  /// An export started before the app was last closed is still being
  /// finished on the phone.
  static const String stillExporting =
      'An earlier export is still being finished. Try again when it’s done.';

  // Success dialog (AC16), wording from _UI_2.png.
  static const String successTitle = 'Download Successful!';
  static String savedAs(String fileName) => 'Saved as $fileName';
  static String savedIn(String location) => 'in $location';
  static const String openFolder = 'Open folder';
  static const String ok = 'OK';

  // Background export (user decision 2026-10-21): the sheet can be closed
  // while the file is made; the bell and a banner say how it went.

  /// Download tapped while another score's export runs: one at a time.
  static String alreadyExporting(String title) =>
      '“$title” is still being exported. You can export this one when it '
      'has finished.';
  static String exportingRow(String title, double fraction) =>
      'Exporting $title… ${percent(fraction)}';
  static String savedRow(String fileName, String location) =>
      'Saved $fileName to $location';
  static String savedToast(String fileName, String location) =>
      '${savedRow(fileName, location)}.';
  static String failedRow(String title) => '$title wasn’t exported';
  static String cancelledRow(String title) => 'Export of $title cancelled';
  static const String failedToastHint = 'Open Export Audio to try again.';
  static const String unread = 'unread';
  static String failedToast(String title) =>
      '${failedRow(title)}. $failedToastHint';

  /// The system notifications' words for [title] (user decision
  /// 2026-10-22), the same as the bell's rows and the banner's.
  static ExportNoticeText notice(String title) => ExportNoticeText(
    exporting: 'Exporting $title…',
    cancel: 'Cancel',
    saved: savedRow(ExportNoticeText.fileSlot, ExportNoticeText.folderSlot),
    failedTitle: failedRow(title),
    failures: {
      'storage_full': storageFull,
      'permission_denied': permissionDenied,
      'generation_failed': generationFailed,
      'interrupted': interrupted,
    },
    fallbackFailure: failedToastHint,
  );

  // Asked once, before the first export's folder pick, on Android 13+.
  static const String notificationsTitle = 'Show export progress?';
  static const String notificationsBody =
      'PiyaNota can show how an export is going in your notifications, so '
      'you can leave the app while it finishes. The export works either '
      'way.';
  static const String notificationsLater = 'Not now';
  static const String notificationsAllow = 'Allow';

  /// What went wrong, in the same words the sheet uses.
  static String failureMessage(ExportFailure failure) => switch (failure) {
    StorageFull() => storageFull,
    PermissionDenied() => permissionDenied,
    GenerationFailed() => generationFailed,
    Interrupted() => interrupted,
    NoFolderPicker() => noFolderPicker,
    // Handled by reopening the picker; only reached if that is bypassed.
    NotLocalFolder() => notLocalFolder,
    StillExporting() => stillExporting,
    Cancelled(:final partialFileLeft) =>
      partialFileLeft ? cancelledPartial : cancelled,
  };
}
