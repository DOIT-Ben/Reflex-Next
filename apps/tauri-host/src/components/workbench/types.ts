export type WorkbenchPhase =
  | "empty"
  | "running"
  | "completed"
  | "error"
  | "cancelled";

export type WorkbenchActionHandler = () => void | Promise<void>;
export type WorkbenchInputHandler = (value: string) => void;
export type WorkbenchRatingHandler = (rating: number) => void | Promise<void>;

export type ConfigSummaryItem = {
  id: string;
  label: string;
  value: string;
  title?: string;
};

export type ResultMetaItem = {
  id: string;
  label: string;
  value: string;
};
