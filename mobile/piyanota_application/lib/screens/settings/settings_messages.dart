import '../capture/capture_messages.dart';

/// Settings copy (PIYA-212). Tests assert on these constants, so change
/// them deliberately. Sentence case throughout: no all-caps group labels.
class SettingsMessages {
  SettingsMessages._();

  static const String title = 'Settings';
  static const String subtitle = 'Your account and playback defaults';

  // Groups.
  static const String accountGroup = 'Account';
  static const String playbackGroup = 'Playback';
  static const String aboutGroup = 'About';

  // AC1.
  static const String email = 'Email';
  // Sessions saved before PIYA-212 carry no email; logging in again
  // stores it.
  static const String emailUnknown = 'Log in again to show your email';

  // AC6.
  static const String changePassword = 'Change password';
  static const String changePasswordHint = 'Current, then new password';
  static const String currentPassword = 'Current password';
  static const String newPassword = 'New password';
  static const String confirmNewPassword = 'Confirm new password';
  static const String currentPasswordRequired = 'Enter your current password';
  // AC6 quotes this wording.
  static const String currentPasswordIncorrect =
      'Your current password is incorrect.';
  static const String changingPassword = 'Changing password…';
  static const String passwordChanged = 'Password changed';
  static const String sessionExpired =
      'Your session has expired. Log in again to change your password.';
  static const String logIn = 'Log in';

  // AC7.
  static const String defaultVoice = 'Default voice';
  static const String defaultVoiceCaption = 'Plays first when you open a score';
  static String voiceSemantics(String voice) => '$voice, default voice';

  // AC8.
  static const String defaultTempo = 'Default tempo';
  static const String defaultTempoCaption =
      'Used when you pick "Not sure" for a new score\'s speed';
  static String tempoValue(int bpm) => CaptureMessages.tempoValue(bpm);
  static String tempoSemanticsValue(int bpm) => '$bpm beats per minute';
  static const String slower = 'Slower';
  static const String faster = 'Faster';

  // AC9. Wording from the plan's design direction (2026-10-17).
  static const String voiceHelpTooltip = 'What does default voice do?';
  static const String voiceHelpBody =
      'This is the voice that plays when you open a score for the first '
      'time. You can still turn other voices on or off on the Playback '
      'screen. You first picked it during setup.';
  static const String tempoHelpTooltip = 'What does default tempo do?';
  static const String tempoHelpBody =
      'When you scan a score and choose "Not sure" for its speed, PiyaNota '
      'makes the audio at this tempo, unless it can read a tempo from the '
      'page. Scores you already scanned keep their tempo. You can still '
      'change the speed on the Playback screen.';

  // AC2.
  static const String appVersion = 'App version';
  static const String versionUnknown = 'Unknown';

  // AC3, AC4.
  static const String logOut = 'Log out';
  static const String logOutTitle = 'Log out of PiyaNota?';
  static const String logOutBody =
      'Your scores stay saved to your account. You will need your email '
      'and password to log back in.';
  static const String cancel = 'Cancel';

  static const String saveFailed =
      "Couldn't save that setting. Please try again.";
}
