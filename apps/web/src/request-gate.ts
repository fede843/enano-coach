export interface RequestToken {
  signal: AbortSignal;
  isCurrent(): boolean;
}

export class RequestGate {
  private readonly controllers = new Map<string, AbortController>();
  private readonly versions = new Map<string, number>();

  begin(key: string): RequestToken {
    this.cancel(key);
    const controller = new AbortController();
    const version = (this.versions.get(key) || 0) + 1;
    this.versions.set(key, version);
    this.controllers.set(key, controller);
    return {
      signal: controller.signal,
      isCurrent: () => this.versions.get(key) === version && !controller.signal.aborted
    };
  }

  cancel(key: string): void {
    this.controllers.get(key)?.abort();
    this.controllers.delete(key);
    this.versions.set(key, (this.versions.get(key) || 0) + 1);
  }

  cancelAll(): void {
    for (const key of this.controllers.keys()) {
      this.cancel(key);
    }
  }
}
