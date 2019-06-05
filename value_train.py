
from itertools import count
import os, random, time, torch
from progress.bar import Bar

from game import Game
from model import ValueModel
from player import ValueModelPlayer, GreedyPlayer
from evaluate import evaluate

def self_play(player, games=1, alpha=0.2, epsilon=0.2, display=False):
    data = []

    for n in Bar('Self play').iter(range(games)):
        game = Game()

        for m in count():
            if display: game.display()
            action, v_prime = player.get_action_and_value(game, epsilon)

            # update the value of the current state
            state = torch.tensor([game.get_state()]).to(player.device)
            value = player.model(state)
            value = value + alpha * (v_prime - value)
            data += [(s, value) for s in game.get_symmetries()]
            data += [(-s, 1-value) for s in game.get_symmetries()]

            game.execute_move(action)
            end_value = game.is_over()

            if end_value:
                if display: game.display()
                data += [(s, end_value) for s in game.get_symmetries()]
                data += [(-s, 1-value) for s in game.get_symmetries()]
                break

            game.flip()

    return data

def batches(data, n):
    l = len(data)
    for i in range(0, l, n):
        x, y = zip(*data[i:min(i + n, l)])
        yield torch.tensor(x), torch.tensor(y)

def train(model, data, lossfn, optimr, device, epochs=10, batch_size=128):
    for epoch in range(epochs):
        random.shuffle(data)

        # train
        model.train()
        for x, y in batches(data, batch_size):
            optimr.zero_grad()
            x, y = x.to(device), y.to(device)
            loss = lossfn(model(x), y)
            loss.backward()
            optimr.step()
            del x, y, loss

        # evaluate
        losses = []
        model.eval()
        with torch.no_grad():
            for x, y in batches(data, batch_size):
                x, y = x.to(device), y.to(device)
                loss = lossfn(model(x), y)
                losses.append(loss.item())
                del x, y, loss

        print('Epoch %d |' % epoch,
              'Loss: %.4e' % (sum(losses)/len(losses)))

def hms(t):
    h, m, s = int(t/60/60), int(t/60)%60, t%60
    if h: return '%dh%02.dm%02.ds' % (h, m, s)
    if m: return '%dm%02.ds' % (m, s)
    return '%.1fs' % s

def main(learn_rate, alpha, epsilon, seed=None):
    if seed:
        torch.manual_seed(seed)
        random.seed(seed)

    # build model, loss function, optimizer, scheduler
    print('\nBuilding model...')
    device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')
    model = ValueModel().to(device)
    if torch.cuda.device_count() >= 1: model = torch.nn.DataParallel(model)
    lossfn = torch.nn.MSELoss()
    optimr = torch.optim.Adam(model.parameters(), lr=learn_rate)
    print(model, 'on', device, 'using', optimr)

    # make players
    model_player = ValueModelPlayer(model, device)
    opponent = GreedyPlayer()

    # keep track of the best model
    best_score = 0, 0, 0
    save_dir = 'results'

    # data queue
    data, data_limit = [], None

    for iteration in count():
        print('\n ==== ITERATION', iteration + 1, '====')

        # save model parameters
        if not os.path.isdir(save_dir): os.mkdir(save_dir)
        torch.save(model.state_dict(),
            os.path.join(save_dir, 'model_' + str(iteration) + '.params'))
        if iteration and score > best_score:
            torch.save(model.state_dict(), os.path.join(save_dir, 'best.params'))
            best_score = score

        # get data from self play
        print()
        start = time.time()
        _epsilon = 0.8*epsilon*2**(-iteration/32) + 0.2*epsilon
        print('Epsilon =', _epsilon)
        new_data = self_play(model_player, 100, alpha, _epsilon)
        data = (data + new_data)[-data_limit:] if data_limit else new_data
        print('Time taken:', hms(time.time() - start))
        print('New data points:', len(new_data))

        # train the model
        print('\nTraining...')
        start = time.time()
        train(model, data, lossfn, optimr, device, 10)
        print('Time taken:', hms(time.time() - start))

        # evaluate against opponent
        print()
        start = time.time()
        score = evaluate(model_player, opponent, 100)
        print('Time taken:', hms(time.time() - start))
        print('%d wins, %d draws, %d losses' % score)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--learn_rate', '-lr', type=float, default=1e-4)
    parser.add_argument('--alpha', '-a', type=float, default=0.2)
    parser.add_argument('--epsilon', '-e', type=float, default=0.5)
    parser.add_argument('--seed', type=int, default=None)
    main(**vars(parser.parse_args()))
