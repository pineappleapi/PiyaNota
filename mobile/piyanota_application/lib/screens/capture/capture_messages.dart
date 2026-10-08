import '../../models/capture_session.dart';
import '../../services/capture/device_channel.dart';
import '../../services/score_upload_api.dart';

/// Every user-facing string on Details and Capture, in plain words for
/// choir members (NFR-3). Upload errors are chosen by `error.code`, never by
/// the server's `message` text (PIYA-101 AC9).
class CaptureMessages {
  CaptureMessages._();

  // Details (step 1).
  static const String detailsTitle = 'Add a score';
  static const String detailsStep = 'Step 1 of 2 · About the song';
  static const String titleLabel = 'Song title';
  static const String titleHint = 'e.g. Bituin Walang Ningning';
  static const String composerLabel = 'Composer or arranger (optional)';
  static const String composerHint = 'e.g. Ryan Cayabyab';
  static const String titleTooLong = 'Use 120 characters or fewer.';
  static const String composerTooLong = 'Use 120 characters or fewer.';
  static const String musicSection =
      'Music details (optional, you can skip these)';
  static const String musicSectionHint =
      'These only label your score. PiyaNota reads the notes from the '
      'pages either way.';
  static const String notSure = 'Not sure';
  static const String keyTile = 'Key';
  static const String keyQuestion =
      'How many ♯ or ♭ are at the start of each line?';
  static const String beatsTile = 'Beats';
  static const String beatsQuestion = 'How is the music counted?';
  static const String speedTile = 'Speed';
  static const String speedQuestion = 'How fast the audio will play';
  static const String speedHint =
      '♩ = quarter notes (beats) per minute. 90 suits most hymns.';
  static const String slow = 'Slow';
  static const String medium = 'Medium';
  static const String fast = 'Fast';
  static const String slower = 'Slower';
  static const String faster = 'Faster';
  static const String done = 'Done';
  static const String cancel = 'Cancel';
  static const String nextAddPages = 'Next: add pages';

  static String tempoValue(int bpm) => '♩ = $bpm';

  // Capture (step 2).
  static const String alignInFrame = 'Align sheet music in frame';
  static const String close = 'Close';
  static const String gallery = 'Gallery';
  static const String pdf = 'PDF';
  static const String camera = 'Camera';
  static const String shutter = 'Take photo';
  static const String flashOn = 'Turn flash on';
  static const String flashOff = 'Turn flash off';
  static const String addPages = 'Add pages';
  static const String addFrom = 'Add pages from';
  static const String scrollLeft = 'Show earlier pages';
  static const String scrollRight = 'Show later pages';
  static const String noPagesYet = 'No pages yet';
  static const String createScore = 'Create score';

  static String pagesLabel(int n) => n == 1 ? '1 page' : '$n pages';
  static String createScoreWith(int n) => '$createScore · ${pagesLabel(n)}';
  static String pageOf(int x, int n) => 'Page $x of $n';
  static String pdfCard(int n) => 'PDF · ${pagesLabel(n)}';
  static String pageSemantics(int x, int n) =>
      'Page $x of $n. Double tap to view. Long press to move.';
  static String pdfSemantics(String name, int n) =>
      'PDF $name, ${pagesLabel(n)}. Double tap to view details.';
  static String editPage(int x) => 'Edit page $x';
  static String removePage(int x) => 'Remove page $x';
  static const String removePdf = 'Remove PDF';
  static const String moveEarlier = 'Move earlier';
  static const String moveLater = 'Move later';
  static String removed(int x) => 'Page $x removed';
  static const String pdfRemoved = 'PDF removed';
  static const String undo = 'Undo';

  static String discardTitle(int n) => 'Discard ${pagesLabel(n)}?';
  static const String discardBody =
      'The pages you added will be lost. Your song details are kept.';
  static const String discard = 'Discard';
  static const String keepEditing = 'Keep editing';

  // Permissions (AC2, AC3).
  static const String cameraNeededTitle = 'Camera is off';
  static const String cameraNeededBody =
      'PiyaNota needs the camera to photograph your sheet music. You can '
      'turn it on in Settings, or add pages from Gallery or PDF.';
  static const String allowCamera = 'Allow camera';
  static const String openSettings = 'Open settings';
  static const String noCamera =
      'No camera is available. Add pages from Gallery or PDF instead.';
  static const String cameraStarting = 'Starting camera';
  static const String cameraPreview = 'Camera preview. Double tap to focus.';
  static const String photosNeededTitle = 'Allow access to photos';
  static const String photosNeededBody =
      'PiyaNota needs permission to read your photos so you can add pages '
      'from your gallery. You can turn it on in Settings.';
  static const String notNow = 'Not now';

  // Adding pages (AC6, AC7, PDF rules).
  static String tooManyPhotos(int added, int picked) =>
      'A score can have up to ${CaptureSession.maxPages} pages. Added '
      '$added of the $picked photos.';
  static const String scoreFull =
      'This score already has ${CaptureSession.maxPages} pages, the most '
      'PiyaNota can read at once.';
  static String pdfTooLong(int pages) =>
      'This PDF has $pages pages. PiyaNota can read up to '
      '${CaptureSession.maxPages} pages at a time. Save the pages you need '
      'as a shorter PDF and try again.';
  static const String notAPdf =
      'That file isn\'t a PDF. Choose a PDF, or add photos instead.';
  static const String pdfEncrypted =
      'This PDF is password-protected. Save a copy without a password and '
      'try again.';
  static const String pdfCorrupt =
      'This PDF couldn\'t be opened. It may be damaged. Try another copy.';
  static const String pdfEmpty = 'This PDF has no pages.';
  static String unreadablePhotos(int n) => n == 1
      ? 'One photo couldn\'t be read, so it wasn\'t added. Use a JPEG or '
            'PNG photo.'
      : '$n photos couldn\'t be read, so they weren\'t added. Use JPEG or '
            'PNG photos.';
  static const String captureFailed =
      'The photo couldn\'t be taken. Please try again.';
  static const String preparingPage = 'Preparing page';

  static const String replacePdfTitle = 'Replace the PDF?';
  static const String replacePdfWithPhotosBody =
      'A score can be photos or one PDF, not both. Remove the PDF and use '
      'photos instead?';
  static const String replacePdfWithPdfBody =
      'A score can have only one PDF. Use the new PDF instead?';
  static String replacePhotosTitle(int n) => 'Replace ${pagesLabel(n)}?';
  static const String replacePhotosBody =
      'A score can be photos or one PDF, not both. Remove your photos and '
      'use this PDF instead?';
  static const String replace = 'Replace';
  static const String keep = 'Keep';

  // Edit Page.
  static const String editTitle = 'Edit page';
  static const String rotate = 'Rotate 90°';
  static const String straighten = 'Straighten';
  static const String reset = 'Reset';
  static const String applyingEdit = 'Saving changes';
  static const String editFailed =
      'The changes couldn\'t be saved. Please try again.';
  static String straightenValue(double degrees) =>
      '${degrees.toStringAsFixed(0)}°';

  // Upload (AC8, PIYA-101 AC9).
  static const String sessionExpired =
      'Your session has expired. Log in again to send this score.';
  static const String logIn = 'Log In';
  static const String network =
      'Couldn\'t reach PiyaNota. Check your internet connection and try '
      'again.';
  static const String generic =
      'Something went wrong sending your score. Please try again.';

  static String uploadError(ScoreUploadException error) => switch (error) {
    UploadSessionExpiredException() => sessionExpired,
    UploadNetworkException() => network,
    UploadRejectedException() => _rejection(error),
  };

  static String _rejection(UploadRejectedException e) {
    // PIYA-101 AC5 numbers pages from 0, like the pipeline's page_index;
    // people count from 1. Reconcile in PIYA-215 if the server changes.
    final page = e.pageIndex == null ? null : e.pageIndex! + 1;
    final wait = _wait(e.retryAfter);
    return switch (e.code) {
      'no_pages' => 'Add at least one page first.',
      'too_many_pages' =>
        'A score can have up to ${CaptureSession.maxPages} pages. Remove '
            'some pages and try again.',
      'mixed_input_types' ||
      'multiple_pdfs' => 'Send either photos or one PDF, not both.',
      'title_required' => 'Go back and add a song title.',
      'title_too_long' =>
        'The song title is too long. Go back and shorten it to 120 '
            'characters or fewer.',
      'title_invalid' =>
        'The song title has characters PiyaNota can\'t save. Go back and '
            'retype it.',
      'composer_too_long' =>
        'The composer name is too long. Go back and shorten it to 120 '
            'characters or fewer.',
      'composer_invalid' =>
        'The composer name has characters PiyaNota can\'t save. Go back '
            'and retype it.',
      'invalid_tempo' || 'invalid_key_signature' || 'invalid_time_signature' =>
        'One of the music details wasn\'t accepted. Go back and set it to '
            '"Not sure".',
      'file_too_large' =>
        page == null
            ? 'This PDF is too large to send. Try a smaller copy.'
            : 'Page $page is too large to send. Crop it or take it again.',
      'image_pixels_too_large' =>
        page == null
            ? 'A page is too large to send. Crop it and try again.'
            : 'Page $page is too large to send. Crop it and try again.',
      'request_too_large' =>
        'These pages are too large to send together. Remove a few pages '
            'and try again.',
      'unsupported_file_type' =>
        page == null
            ? 'One of the pages isn\'t a JPEG or PNG photo. Remove it and '
                  'add it again.'
            : 'Page $page isn\'t a JPEG or PNG photo. Remove it and add it '
                  'again.',
      'corrupt_image' =>
        page == null
            ? 'One of the pages couldn\'t be read. Remove it and add it '
                  'again.'
            : 'Page $page couldn\'t be read. Remove it and add it again.',
      'corrupt_or_encrypted_pdf' =>
        'This PDF couldn\'t be opened. It may be damaged or '
            'password-protected. Try another copy.',
      'rate_limited' =>
        'You\'ve sent several scores in a row. Please wait $wait and try '
            'again.',
      'queue_full' =>
        'PiyaNota is busy with other scores right now. Please try again in '
            '$wait.',
      _ => generic,
    };
  }

  static String _wait(Duration? retryAfter) {
    if (retryAfter == null) return 'a few minutes';
    final seconds = retryAfter.inSeconds;
    if (seconds < 60) {
      return seconds <= 1 ? 'a moment' : '$seconds seconds';
    }
    final minutes = (seconds / 60).ceil();
    return minutes == 1 ? '1 minute' : '$minutes minutes';
  }

  static String pdfProblem(PdfProblem problem) => switch (problem) {
    PdfProblem.encrypted => pdfEncrypted,
    PdfProblem.corrupt => pdfCorrupt,
  };
}
