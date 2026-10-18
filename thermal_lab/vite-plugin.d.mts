/** Static workstream assets served in development and copied into GitHub Pages builds. */
export default function thermalLab(): {
  name: string;
  configResolved(config: unknown): void;
  configureServer(server: unknown): void;
  generateBundle(): void;
};
