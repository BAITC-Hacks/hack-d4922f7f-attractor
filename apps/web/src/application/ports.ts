import type { Alternative, Catalog, Evaluation, Selection } from "../domain/types";

export interface V1Api {
  getCatalog(signal?: AbortSignal): Promise<Catalog>;
  validate(selections: Selection[], signal?: AbortSignal): Promise<Evaluation>;
  evaluate(selections: Selection[], signal?: AbortSignal): Promise<Evaluation>;
  alternatives(selections: Selection[], signal?: AbortSignal): Promise<Alternative[]>;
}
