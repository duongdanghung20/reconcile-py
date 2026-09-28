# Typed records are the core contract; pandas is an edge adapter

The engine's public API accepts and returns typed records (dataclasses), not pandas `DataFrame`s. A thin, optional adapter (`from_dataframe` / `to_dataframe`) bridges pandas at the IO edge for callers who have their data in frames.

We chose this over a pandas-native API because deterministic, replayable matching and a genuinely typed public surface are the product's promises, and pandas dtype coercion (NaN, object columns, float money) undermines both. The trade-off: pandas users pay one adapter call at each boundary instead of passing frames straight through.
