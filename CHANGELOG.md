# Release notes

## v0.2.0

### Feat

- Citry now logs through the standard `logging` module, under the `"citry"`
  logger, with a `TRACE` level (5, below `DEBUG`). The logger traces each component,
  slot, and node as it renders. Turn it on to debug a render:

  ```python
  import logging
  logging.getLogger("citry").setLevel(5)
  ```

## v0.1.0

_30 Jun 2026_

Initial release.

## 2025-12-21

Initial commit.

This project was forked from [django-components/djc-core](https://github.com/django-components/djc-core) at commit [49e20dc](https://github.com/django-components/djc-core/commit/49e20dc).
