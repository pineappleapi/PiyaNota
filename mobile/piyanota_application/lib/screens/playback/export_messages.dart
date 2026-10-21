import '../../models/voice_part.dart';

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

  // Success dialog (AC16), wording from _UI_2.png.
  static const String successTitle = 'Download Successful!';
  static String savedAs(String fileName) => 'Saved as $fileName';
  static String savedIn(String location) => 'in $location';
  static const String openFolder = 'Open folder';
  static const String ok = 'OK';
}
