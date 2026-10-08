/// Named route constants. Onboarding itself is the app's `home` (not a
/// named route) since it's a one-time gate, not something re-navigated to.
class AppRoutes {
  AppRoutes._();

  static const login = '/login';
  static const signUp = '/sign-up';
  static const passwordReset = '/password-reset';
  static const scoreLibrary = '/library';

  // Destinations from the Score Library (PIYA-205 AC7/AC8). They route to
  // ComingSoon placeholders until PIYA-206/208/212 land; the route names
  // and arguments are the contract those screens must keep.
  static const playback = '/playback';
  static const capture = '/capture';
  static const settings = '/settings';
}

/// Arguments for [AppRoutes.playback]. Carries the id of an already
/// processed score, so Playback loads its existing audio rather than
/// re-running the pipeline (PIYA-205 AC7). [title] is only for the app bar
/// while Playback fetches the rest.
class PlaybackArguments {
  const PlaybackArguments({required this.scoreId, required this.title});

  final int scoreId;
  final String title;
}
