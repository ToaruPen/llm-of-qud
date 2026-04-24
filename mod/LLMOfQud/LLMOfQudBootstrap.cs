using XRL;
using XRL.World;

namespace LLMOfQud
{
    [PlayerMutator]
    public class LLMOfQudBootstrap : IPlayerMutator
    {
        public void mutate(GameObject player)
        {
            The.Game.RequireSystem<LLMOfQudSystem>();
        }
    }
}
