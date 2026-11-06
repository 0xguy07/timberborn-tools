using Bindito.Core;

namespace BeaverBridge
{
    /// <summary>
    /// Registers the bridge in the Game context. Timberborn discovers every
    /// Configurator in a mod assembly and runs the ones whose context matches.
    /// </summary>
    [Context("Game")]
    public class BridgeConfigurator : Configurator
    {
        protected override void Configure()
        {
            Bind<GameApi>().AsSingleton();
            Bind<BridgeServer>().AsSingleton();
        }
    }
}
