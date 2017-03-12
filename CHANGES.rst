=======
Changes
=======

0.2.0 (2017-03-12)
==================

- Make use of newer support in buildout for per-extension binary dist UNPACKERs
  for a much cleaner implementation of wheel support.

- Also, make use of newer support in buildout for installed non-egg
  distributions to get rid of humpty as dependency. Wheel packages will be
  installed as ``.ovo`` directories inside ``eggs-directory``.

0.1.2 (2017-02-13)
==================

Initial release
